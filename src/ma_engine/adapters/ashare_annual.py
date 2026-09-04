"""Point-in-time A-share adapter: companies as they stood at a fiscal
year end, read from their annual reports.

The live A-share adapter reads today's roster, which is wrong for a
backtest: a company that changed hands last year now shows the buyer's
chairman and controller. The annual report for an earlier fiscal year
is the only free source that says who ran the company then. It
carries the director and officer table with ages, the chairman's
appointment date on the Shanghai layout, a birth year in most
Shenzhen resumes, and the mandatory controlling-shareholder and
actual-controller sections.

Reports are fetched through cninfo's public announcement search and
static file server, which need no login. Parsing a 200-page PDF takes
20 to 45 seconds, so results are cached and the work is threaded.
"""

from __future__ import annotations

import io
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Optional

from ma_engine.adapters.ashare import (
    NOT_A_PERSON,
    STATE_PAT,
    CENTRAL_SOE_PAT,
    UA,
    _Client,
    _num,
    _year,
    classify_ownership,
)
from ma_engine.adapters.base import Adapter, Company, Person

CNINFO_QUERY = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STOCKS = "http://www.cninfo.com.cn/new/data/szse_stock.json"
CNINFO_STATIC = "http://static.cninfo.com.cn/"

_TAG = re.compile(r"</?em>")

# Shenzhen annual-report layout: 姓名 性别 年龄 职务 任职状态
_ROW_SZSE = re.compile(
    r"([一-龥]{2,4})\s+(男|女)\s+(\d{2})\s+([^\s]{2,30}?)\s+(现任|离任)")
# Shanghai layout: 姓名 职务 性别 年龄 任期起始日期
_ROW_SSE = re.compile(
    r"([一-龥]{2,4})\s+([^\s\d]{2,20}?)\s*(?:（(离任|现任)）)?"
    r"\s+(男|女)\s+(\d{2})\s+(\d{4})[/年](\d{1,2})")
# Birth year inside a resume: 时沈祥先生：1963年 8月出生
_BIRTH = re.compile(r"([一-龥]{2,4})(?:先生|女士)[：:，,]?\s*(19\d{2}|20\d{2})\s*年")
_NAME = re.compile(r"[一-龥]{2,4}")


def cninfo_session():
    import requests

    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
        "X-Requested-With": "XMLHttpRequest",
    })
    return s


def orgid_map(session) -> dict[str, dict]:
    """Code to cninfo org id. The id is not derivable from the code, and a
    per-company query silently returns nothing without it."""
    lst = session.get(CNINFO_STOCKS, timeout=120).json()
    if isinstance(lst, dict):
        lst = lst.get("stockList", [])
    return {x["code"]: x for x in lst}


def cninfo_search(session, searchkey: str, se_date: str, code: str | None = None,
                  orgid: str | None = None, category: str = "") -> list[dict]:
    """Title search on cninfo. Page size is capped at 30 and paging past
    the end repeats earlier pages, so this stops on the reported total or
    on the first page with nothing new."""
    stock = f"{code},{orgid}" if code and orgid else ""
    seen: set = set()
    out: list[dict] = []
    page, total = 1, None
    while True:
        form = {"pageNum": page, "pageSize": 30, "column": "szse",
                "tabName": "fulltext", "plate": "", "stock": stock,
                "searchkey": searchkey, "secid": "", "category": category,
                "trade": "", "seDate": se_date, "sortName": "", "sortType": "",
                "isHLtitle": "true"}
        payload = None
        for attempt in range(4):
            try:
                payload = session.post(CNINFO_QUERY, data=form, timeout=90).json()
                break
            except Exception:  # noqa: BLE001 - network, retry
                if attempt == 3:
                    raise
                time.sleep(3)
        if total is None:
            total = payload.get("totalRecordNum") or 0
        fresh = [a for a in (payload.get("announcements") or [])
                 if a["announcementId"] not in seen]
        if not fresh:
            break
        for a in fresh:
            seen.add(a["announcementId"])
            out.append({
                "code": a["secCode"], "name": a["secName"],
                "date": time.strftime("%Y-%m-%d",
                                      time.localtime(a["announcementTime"] / 1000)),
                "title": _TAG.sub("", a["announcementTitle"]),
                "id": a["announcementId"], "url": a["adjunctUrl"],
            })
        if len(out) >= total or page > (total // 30) + 3:
            break
        page += 1
    return out


def annual_report_url(session, code: str, fiscal_year: int, orgid: str
                      ) -> tuple[Optional[str], Optional[str]]:
    rows = cninfo_search(session, "年度报告",
                         f"{fiscal_year + 1}-01-01~{fiscal_year + 1}-12-31",
                         code=code, orgid=orgid, category="category_ndbg_szsh")
    for r in rows:
        t = r["title"]
        if str(fiscal_year) in t and not any(
                k in t for k in ("摘要", "英文", "更正", "已取消", "补充")):
            return CNINFO_STATIC + r["url"], t
    return None, None


def pdf_text(url: str) -> str:
    import requests
    from pypdf import PdfReader

    r = requests.get(url, headers={"User-Agent": UA}, timeout=300)
    reader = PdfReader(io.BytesIO(r.content))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - a bad page should not lose the report
            parts.append("")
    return "\n".join(parts)


def parse_annual_report(text: str) -> dict[str, Any]:
    """Pull the board table, the chairman, and the controller sections
    out of annual-report text. Handles both exchange layouts."""
    rows: list[dict] = []
    for m in _ROW_SZSE.finditer(text):
        rows.append(dict(name=m.group(1), sex=m.group(2), age=int(m.group(3)),
                         pos=m.group(4), status=m.group(5), since=None))
    for m in _ROW_SSE.finditer(text):
        rows.append(dict(name=m.group(1), sex=m.group(4), age=int(m.group(5)),
                         pos=m.group(2), status=m.group(3) or "现任",
                         since=int(m.group(6))))
    births = {m.group(1): int(m.group(2)) for m in _BIRTH.finditer(text)}

    seen: set = set()
    officers: list[dict] = []
    for r in rows:
        key = (r["name"], r["pos"])
        if key in seen:
            continue
        seen.add(key)
        r["birth_year"] = births.get(r["name"])
        officers.append(r)

    chairmen = [r for r in officers
                if "董事长" in r["pos"] and "副董事长" not in r["pos"]
                and "助理" not in r["pos"] and "办公室" not in r["pos"]
                and r["status"] != "离任"]
    if not chairmen:
        chairmen = [r for r in officers if "董事长" in r["pos"]
                    and "副董事长" not in r["pos"]]

    def block(*keys: str, width: int = 520) -> Optional[str]:
        for k in keys:
            i = text.find(k)
            if i >= 0:
                return re.sub(r"\s+", " ", text[i:i + width])
        return None

    return {
        "chairman": chairmen[0] if chairmen else None,
        "officers": officers,
        "controlling_shareholder": block("控股股东性质", "控股股东情况"),
        "actual_controller": block("实际控制人性质", "(二) 实际控制人情况",
                                   "实际控制人情况"),
    }


def controller_from_block(block: Optional[str], officers: list[dict],
                          chairman: Optional[dict]) -> tuple[list[str], str]:
    """Work out who the actual controller was from the report's own
    section. Returns (names, ownership type). Natural-person controllers
    are matched against the board table where possible; a section that
    says 自然人 with no matchable name falls back to the chairman."""
    if not block:
        return [], "未知"
    if STATE_PAT.search(block) or CENTRAL_SOE_PAT.search(block):
        return [], "国企"
    board = {o["name"] for o in officers}
    names = [n for n in dict.fromkeys(_NAME.findall(block)) if n in board]
    names = [n for n in names if not any(t in n for t in NOT_A_PERSON)]
    if names:
        return names, "民营"
    if "自然人" in block and chairman:
        return [chairman["name"]], "民营"
    if "无实际控制人" in block:
        return [], "无实际控制人"
    return [], "集体或其他法人"


class AShareAnnualAdapter(Adapter):
    """Companies as of 31 December of `fiscal_year`, from annual reports.

    `codes` is the population to build. Records that could not be read
    are kept in `self.failures` with the reason, so coverage is known.
    """

    name = "ashare_annual"

    def __init__(self, codes: Iterable[str], fiscal_year: int,
                 cache_path: str | Path | None = None, workers: int = 8,
                 progress: bool = True, private_only: bool = True):
        self.codes = [str(c).zfill(6) for c in codes]
        self.fiscal_year = fiscal_year
        self.cache_path = Path(cache_path) if cache_path else None
        self.workers = workers
        self.progress = progress
        self.private_only = private_only
        self.failures: dict[str, str] = {}
        self._local = threading.local()
        self.em = _Client()

    # -- bulk, point-in-time where the source allows it ------------------

    def financials(self) -> dict[str, dict]:
        rows = self.em.report("RPT_LICO_FN_CPD",
                              filter=f"(REPORTDATE='{self.fiscal_year}-12-31')",
                              sortColumns="SECURITY_CODE", sortTypes="1")
        return {str(r.get("SECURITY_CODE")): r for r in rows}

    def pledges(self, on_or_before: str) -> dict[str, float]:
        """Pledge ratios from the latest weekly file on or before a date.

        The pledge table is 1.6 million rows and a sorted range query
        hangs on the server, so this asks for exact dates, stepping back
        one day at a time until a weekly file answers.
        """
        import datetime as dt

        day = dt.date.fromisoformat(on_or_before)
        for _ in range(14):
            rows = self.em.report("RPT_CSDC_LIST", page_size=500,
                                  filter=f"(TRADE_DATE='{day.isoformat()}')")
            if rows:
                out = {}
                for r in rows:
                    ratio = _num(r.get("PLEDGE_RATIO"))
                    if ratio is not None:
                        out[str(r.get("SECURITY_CODE"))] = ratio / 100.0
                self.pledge_date = day.isoformat()
                return out
            day -= dt.timedelta(days=1)
        self.pledge_date = None
        return {}

    def org_info(self) -> dict[str, dict]:
        rows = self.em.report("RPT_F10_ORG_BASICINFO")
        return {str(r.get("SECURITY_CODE")): r for r in rows}

    # -- per company -----------------------------------------------------

    @property
    def session(self):
        if not hasattr(self._local, "s"):
            self._local.s = cninfo_session()
        return self._local.s

    def _read_one(self, code: str, orgid: str) -> dict:
        try:
            url, title = annual_report_url(self.session, code, self.fiscal_year, orgid)
            if not url:
                return {"code": code, "error": "no annual report found"}
            parsed = parse_annual_report(pdf_text(url))
            if not parsed["officers"]:
                return {"code": code, "error": "board table not found", "report": title}
            return {"code": code, "report": title, **parsed}
        except Exception as exc:  # noqa: BLE001 - one bad PDF must not stop the run
            return {"code": code, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    def companies(self) -> Iterable[Company]:
        if self.cache_path and self.cache_path.exists():
            yield from self._from_cache()
            return

        if self.progress:
            print(f"Loading FY{self.fiscal_year} financials, pledges and org info...",
                  flush=True)
        session = cninfo_session()
        orgids = orgid_map(session)
        if self.progress:
            print(f"  cninfo org ids: {len(orgids)}", flush=True)
        fins = self.financials()
        if self.progress:
            print(f"  financials for FY{self.fiscal_year}: {len(fins)}", flush=True)
        pledged = self.pledges(f"{self.fiscal_year + 1}-04-30")
        if self.progress:
            print(f"  pledge file dated {self.pledge_date}: {len(pledged)} companies",
                  flush=True)
        org = self.org_info()
        if self.progress:
            print(f"  org info: {len(org)}", flush=True)

        todo = [(c, orgids[c]["orgId"]) for c in self.codes if c in orgids]
        for c in self.codes:
            if c not in orgids:
                self.failures[c] = "unknown to cninfo"
        if self.progress:
            print(f"Reading {len(todo)} annual reports with {self.workers} "
                  f"workers (20-45 s each)...", flush=True)

        built: list[Company] = []
        done = 0
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for parsed in pool.map(lambda t: self._read_one(*t), todo):
                done += 1
                if self.progress and done % 25 == 0:
                    print(f"  {done}/{len(todo)} reports read, "
                          f"{len(self.failures)} failures", flush=True)
                code = parsed["code"]
                if parsed.get("error"):
                    self.failures[code] = parsed["error"]
                    continue
                company = self._build(code, parsed, orgids.get(code, {}),
                                      org.get(code, {}), fins.get(code, {}),
                                      pledged.get(code, 0.0))
                if company is None:
                    continue
                built.append(company)
                if self.cache_path and len(built) % 50 == 0:
                    self._write_cache(built)      # checkpoint; a crash keeps these
                yield company

        if self.cache_path:
            self._write_cache(built)
        if self.progress:
            print(f"Built {len(built)} companies; {len(self.failures)} could "
                  f"not be read.", flush=True)

    def _build(self, code: str, parsed: dict, meta: dict, org: dict,
               fin: dict, pledge_ratio: float) -> Company | None:
        officers = parsed["officers"]
        chairman = parsed["chairman"]
        names, ownership = controller_from_block(parsed["actual_controller"],
                                                 officers, chairman)
        if self.private_only and ownership != "民营":
            self.failures[code] = f"not privately controlled ({ownership})"
            return None

        ages = {o["name"]: o["age"] for o in officers}
        executives = [Person(name=o["name"], role=o["pos"], age=o["age"])
                      for o in officers]
        shareholders = [Person(name=n, role="实际控制人", age=ages.get(n))
                        for n in names]

        revenue = _num(fin.get("TOTAL_OPERATE_INCOME"))
        profit = _num(fin.get("PARENT_NETPROFIT"))
        return Company(
            name=meta.get("zwjc") or org.get("SECURITY_NAME_ABBR") or code,
            industry=fin.get("BOARD_NAME") or "",
            region=org.get("REGIONBK") or "",
            founded_year=_year(org.get("FOUND_DATE")),
            legal_rep=chairman["name"] if chairman else "",
            legal_rep_since=(chairman or {}).get("since"),
            shareholders=shareholders,
            executives=executives,
            revenue_m=revenue / 1e6 if revenue else None,
            net_profit_m=profit / 1e6 if profit else None,
            pledge_ratio=pledge_ratio,
            is_private=True,
            source=f"ashare:{code}",
        )

    # -- cache, same format as the live adapter ---------------------------

    def _write_cache(self, companies: list[Company]) -> None:
        import dataclasses

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"fiscal_year": self.fiscal_year,
                   "failures": self.failures,
                   "companies": [dataclasses.asdict(c) for c in companies]}
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                   encoding="utf-8")

    def _from_cache(self) -> Iterable[Company]:
        raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.failures = raw.get("failures", {})
        for item in raw["companies"]:
            item["shareholders"] = [Person(**p) for p in item.get("shareholders", [])]
            item["executives"] = [Person(**p) for p in item.get("executives", [])]
            yield Company(**item)
