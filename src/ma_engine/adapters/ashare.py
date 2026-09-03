"""A-share adapter: the one segment of the Chinese market where owner
age is public.

Listed companies must disclose their directors' and executives' exact
ages. That makes the roughly five thousand A-share companies the only
population where this engine's most important signal can be read
rather than estimated. Among them, the private, family-controlled
ones are real succession candidates. Over three hundred A-share
private-company chairmen are already past 65.

Everything here uses free, public disclosure endpoints. No credentials,
no scraping behind a login, no anti-bot circumvention.

One hard-won implementation note. From outside mainland China these
endpoints are not blocked, but opening a new TLS connection to them
costs about forty seconds, while reusing an open one costs a fraction
of a second. So every request goes through a persistent session, one
per thread. This is why the obvious library wrappers appear to hang
from abroad: they open a fresh connection per call.
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Optional

from ma_engine.adapters.base import Adapter, Company, Person

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

EMWEB = "https://emweb.securities.eastmoney.com/PC_HSF10"
DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"
SCREENER = "https://data.eastmoney.com/dataapi/xuangu/list"

BIRTH_RE = re.compile(r"(19\d{2}|20\d{2})\s*年.{0,3}出生")

# Markers that identify a state-linked controlling entity. Ownership
# type is not published as a field anywhere free, so it is inferred
# from the name of the actual controller, the same convention the
# academic databases use.
STATE_PAT = re.compile(
    "国务院|国资委|国有资产监督管理|国有资产管理|财政部|财政局|"
    "人民政府|省政府|市政府|县政府|地方政府|管理委员会|"
    "中央汇金|汇金公司|社保基金|全民所有制|国资|国有独资|"
    "教育部|工业和信息化部|中国科学院|中国农业科学院|供销合作总社|"
    "党委|军委|铁道部|交通运输部|卫生健康委|"
    "开发区管委会|高新区管委会|城投|国投|国控")

CENTRAL_SOE_PAT = re.compile(
    "^中国(石油|石化|海洋石油|移动|联通|电信|华能|大唐|华电|国电|"
    "南方电网|国家电网|兵器|航空工业|航天科技|航天科工|船舶|电子科技|"
    "中车|中化|五矿|宝武|铝业|黄金|建筑|中铁|铁建|交通建设|能源建设|"
    "核工业|广核|长江三峡|烟草|邮政|供销|盐业|保利|华润|招商局|"
    "国新控股|诚通控股)")

FOREIGN_PAT = re.compile(
    r"Limited|LIMITED|Ltd|LTD|Inc|INC|Corp|CORP|Holdings|HOLDINGS|"
    r"B\.?V\.?|N\.?V\.?|S\.?A\.?|GmbH|Pte|PLC|外商|外资|BVI|开曼|Cayman")

# One or more Chinese personal names, separated by commas or slashes.
PERSON_PAT = re.compile(r"^[一-龥]{2,4}([,，、\s/]+[一-龥]{2,4})*$")

NOT_A_PERSON = ("公司", "集团", "企业", "厂", "研究院", "大学", "学院", "医院",
                "银行", "基金", "中心", "协会", "工会", "合作社", "委员会",
                "管理局", "投资", "控股", "实业", "科技", "有限")


def classify_ownership(controller_name: str) -> str:
    """Infer the ownership type from the actual controller's name.

    Returns one of: 民营 (private, person-controlled), 国企 (state),
    外资 (foreign), 集体或其他法人 (other legal person), or
    无实际控制人 (no actual controller).

    Known limitation: where the controller is an intermediate holding
    company whose name carries no state marker, this returns
    集体或其他法人 rather than resolving the chain upward.
    """
    s = (controller_name or "").strip()
    if not s or s in {"-", "--", "无", "无实际控制人", "None"}:
        return "无实际控制人"
    if STATE_PAT.search(s) or CENTRAL_SOE_PAT.search(s):
        return "国企"
    if FOREIGN_PAT.search(s):
        return "外资"
    if not any(t in s for t in NOT_A_PERSON) and PERSON_PAT.match(s):
        return "民营"
    return "集体或其他法人"


def em_code(code: str) -> str:
    """Add the exchange prefix Eastmoney expects, e.g. 002714 -> SZ002714."""
    code = str(code).zfill(6)
    if code.startswith(("60", "68", "900")):
        return "SH" + code
    if code.startswith(("43", "83", "87", "88", "920")):
        return "BJ" + code
    return "SZ" + code


class _Client:
    """Thread-local persistent sessions. The whole performance story."""

    def __init__(self, timeout: int = 60):
        self._local = threading.local()
        self.timeout = timeout

    @property
    def session(self):
        import requests

        if not hasattr(self._local, "s"):
            self._local.s = requests.Session()
            self._local.s.headers.update({"User-Agent": UA})
        return self._local.s

    def get_json(self, url: str, params: dict | None = None,
                 retries: int = 3) -> Any:
        last = None
        for attempt in range(retries):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 200:
                    return r.json()
                last = f"HTTP {r.status_code}"
            except Exception as exc:  # noqa: BLE001 - network layer, report and retry
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"{url} failed after {retries} attempts: {last}")

    def report(self, report_name: str, page_size: int = 500,
               max_pages: int | None = None, **extra) -> list[dict]:
        """Read a paginated Eastmoney datacenter report."""
        rows: list[dict] = []
        page = 1
        while True:
            params = {"reportName": report_name, "columns": "ALL",
                      "pageSize": str(page_size), "pageNumber": str(page),
                      "source": "WEB", "client": "WEB"}
            params.update(extra)
            payload = self.get_json(DATACENTER, params)
            if not payload.get("success") or not payload.get("result"):
                break
            rows.extend(payload["result"]["data"])
            pages = payload["result"].get("pages", 1)
            if page >= pages or (max_pages and page >= max_pages):
                break
            page += 1
        return rows


def _num(value: Any) -> Optional[float]:
    try:
        if value in (None, "", "-", "--"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _year(value: Any) -> Optional[int]:
    m = re.match(r"(\d{4})", str(value or ""))
    return int(m.group(1)) if m else None


class AShareAdapter(Adapter):
    """Build Company records for A-share companies.

    By default it keeps only privately (person) controlled companies,
    which is the population this project is about.
    """

    name = "ashare"

    def __init__(self, limit: int | None = None, workers: int = 16,
                 private_only: bool = True, cache_path: str | Path | None = None,
                 report_date: str = "2025-06-30", progress: bool = True):
        self.limit = limit
        self.workers = workers
        self.private_only = private_only
        self.cache_path = Path(cache_path) if cache_path else None
        self.report_date = report_date
        self.progress = progress
        self.client = _Client()

    # -- bulk endpoints, one call each for the whole market -------------

    def universe(self, page_size: int = 500) -> list[dict]:
        """Codes, names, industry, listing date, market cap.

        This endpoint reports a total in `count` but does not return a
        `pages` field, so paging is driven by the total and by short
        pages, never by `pages`.
        """
        rows: list[dict] = []
        page = 1
        total: int | None = None
        while True:
            payload = self.client.get_json(SCREENER, {
                "st": "SECURITY_CODE", "sr": "1", "ps": str(page_size),
                "p": str(page),
                "sty": "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,NEW_PRICE,"
                       "TOTAL_MARKET_CAP,LISTING_DATE,INDUSTRY",
                "filter": "", "source": "SELECT_SECURITIES", "client": "WEB"})
            result = payload.get("result") or {}
            data = result.get("data") or []
            if not payload.get("success") or not data:
                break
            rows.extend(data)
            if total is None:
                total = result.get("count")
            if len(data) < page_size or (total and len(rows) >= total):
                break
            page += 1
        return rows

    def org_info(self) -> dict[str, dict]:
        """Chairman, region, founding date, employee count, per company."""
        rows = self.client.report("RPT_F10_ORG_BASICINFO")
        return {str(r.get("SECURITY_CODE")): r for r in rows}

    def financials(self) -> dict[str, dict]:
        rows = self.client.report(
            "RPT_LICO_FN_CPD",
            filter=f"(REPORTDATE='{self.report_date}')",
            sortColumns="SECURITY_CODE", sortTypes="1")
        return {str(r.get("SECURITY_CODE")): r for r in rows}

    def pledges(self) -> dict[str, float]:
        """Latest weekly equity-pledge snapshot, as a ratio from 0 to 1."""
        payload = self.client.get_json(DATACENTER, {
            "reportName": "RPT_CSDC_LIST", "columns": "TRADE_DATE",
            "pageSize": "1", "pageNumber": "1", "sortColumns": "TRADE_DATE",
            "sortTypes": "-1", "source": "WEB", "client": "WEB"})
        trade_date = payload["result"]["data"][0]["TRADE_DATE"][:10]
        rows = self.client.report(
            "RPT_CSDC_LIST", filter=f"(TRADE_DATE='{trade_date}')",
            sortColumns="PLEDGE_RATIO", sortTypes="-1")
        out = {}
        for r in rows:
            ratio = _num(r.get("PLEDGE_RATIO"))
            if ratio is not None:
                out[str(r.get("SECURITY_CODE"))] = ratio / 100.0
        return out

    # -- per-company endpoints, fetched concurrently --------------------

    def _controller_and_chairman(self, code: str) -> dict:
        """One company: actual controller plus the chairman's age."""
        result: dict[str, Any] = {"code": code}
        try:
            payload = self.client.get_json(
                f"{EMWEB}/ShareholderResearch/PageAjax", {"code": em_code(code)})
            controllers = payload.get("sjkzr") or []
            if controllers:
                result["controller"] = controllers[0].get("HOLDER_NAME")
                result["controller_pct"] = _num(controllers[0].get("HOLD_RATIO"))
            result["top10"] = [
                {"name": h.get("HOLDER_NAME"),
                 "pct": _num(h.get("HOLD_NUM_RATIO"))}
                for h in (payload.get("sdgd") or [])[:10]
            ]
        except RuntimeError as exc:
            result["error"] = str(exc)

        try:
            payload = self.client.get_json(
                f"{EMWEB}/CompanyManagement/PageAjax", {"code": em_code(code)})
            execs = payload.get("gglb") or []
            result["executives"] = [
                {"name": e.get("PERSON_NAME"),
                 "position": e.get("POSITION"),
                 "age": int(_num(e.get("AGE"))) if _num(e.get("AGE")) else None,
                 "birth_year": (lambda m: int(m.group(1)) if m else None)(
                     BIRTH_RE.search(str(e.get("RESUME") or ""))),
                 "since": e.get("INCUMBENT_TIME")}
                for e in execs
            ]
        except RuntimeError as exc:
            result.setdefault("error", str(exc))
        return result

    def _fetch_details(self, codes: list[str]) -> dict[str, dict]:
        done = 0
        out: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for detail in pool.map(self._controller_and_chairman, codes):
                out[detail["code"]] = detail
                done += 1
                if self.progress and done % 50 == 0:
                    print(f"  fetched {done}/{len(codes)} companies", flush=True)
        return out

    # -- assembly -------------------------------------------------------

    def companies(self) -> Iterable[Company]:
        if self.cache_path and self.cache_path.exists():
            yield from self._from_cache()
            return

        if self.progress:
            print("Loading A-share universe, financials and pledges...", flush=True)
        universe = self.universe()
        org = self.org_info()
        fins = self.financials()
        pledged = self.pledges()

        codes = [str(r.get("SECURITY_CODE")) for r in universe]
        if self.limit:
            codes = codes[: self.limit]
        if self.progress:
            print(f"Fetching controller and executive detail for {len(codes)} "
                  f"companies...", flush=True)
        details = self._fetch_details(codes)

        by_code = {str(r.get("SECURITY_CODE")): r for r in universe}
        built = []
        for code in codes:
            company = self._build(code, by_code.get(code, {}), org.get(code, {}),
                                  fins.get(code, {}), pledged.get(code, 0.0),
                                  details.get(code, {}))
            if company is None:
                continue
            built.append(company)
            yield company

        if self.cache_path:
            self._write_cache(built)

    def _build(self, code: str, uni: dict, org: dict, fin: dict,
               pledge_ratio: float, detail: dict) -> Company | None:
        controller = detail.get("controller")
        ownership = classify_ownership(controller)
        if self.private_only and ownership != "民营":
            return None

        executives = detail.get("executives") or []
        chairman = next((e for e in executives
                         if "董事长" in (e.get("position") or "")), None)

        people: list[Person] = []
        for e in executives:
            age = e.get("age")
            if age is None and e.get("birth_year"):
                age = time.localtime().tm_year - e["birth_year"]
            people.append(Person(name=e.get("name") or "",
                                 role=e.get("position") or "",
                                 age=age))

        shareholders: list[Person] = []
        if controller:
            # The controller may be several named individuals.
            for part in re.split(r"[,，、/\s]+", controller):
                if not part:
                    continue
                match = next((p for p in people if p.name == part), None)
                shareholders.append(Person(
                    name=part, role="实际控制人",
                    ownership_pct=detail.get("controller_pct") or 0.0,
                    age=match.age if match else None))
        for holder in detail.get("top10") or []:
            nm = holder.get("name") or ""
            if not nm or any(s.name == nm for s in shareholders):
                continue
            is_company = any(t in nm for t in NOT_A_PERSON)
            shareholders.append(Person(name=nm, role="十大股东",
                                       ownership_pct=holder.get("pct") or 0.0,
                                       is_company=is_company))

        revenue = _num(fin.get("TOTAL_OPERATE_INCOME"))
        profit = _num(fin.get("PARENT_NETPROFIT"))
        founded = _year(org.get("FOUND_DATE") or uni.get("LISTING_DATE"))
        since = _year(chairman.get("since")) if chairman else None

        return Company(
            name=uni.get("SECURITY_NAME_ABBR") or org.get("ORG_NAME") or code,
            industry=uni.get("INDUSTRY") or fin.get("BOARD_NAME") or "",
            region=org.get("REGIONBK") or "",
            founded_year=founded,
            legal_rep=(chairman or {}).get("name") or org.get("CHAIRMAN") or "",
            # Only a real appointment date counts as tenure. The signal
            # falls back to the founding year itself, at lower
            # confidence, rather than us asserting a tenure we cannot see.
            legal_rep_since=since,
            shareholders=shareholders,
            executives=people,
            revenue_m=revenue / 1e6 if revenue else None,
            net_profit_m=profit / 1e6 if profit else None,
            pledge_ratio=pledge_ratio,
            is_private=ownership == "民营",
            source=f"ashare:{code}",
        )

    # -- cache ----------------------------------------------------------

    def _write_cache(self, companies: list[Company]) -> None:
        import dataclasses

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [dataclasses.asdict(c) for c in companies]
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        if self.progress:
            print(f"Wrote {len(companies)} companies to {self.cache_path}",
                  flush=True)

    def _from_cache(self) -> Iterable[Company]:
        raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        for item in raw:
            item["shareholders"] = [Person(**p) for p in item.get("shareholders", [])]
            item["executives"] = [Person(**p) for p in item.get("executives", [])]
            yield Company(**item)
