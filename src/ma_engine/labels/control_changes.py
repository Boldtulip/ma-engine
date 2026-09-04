"""Labels from public announcements: which listed companies came up for
sale, and when.

A change of control at a listed company in China is announced in
stages: a suspension notice while the deal is planned, a rights-change
notice, a completion notice. The announcements are searchable by title
on cninfo. This module collects them, groups them into one episode per
company and deal, and turns episodes into labels for a scoring date
and an outcome window.

The label is "came up for sale", not "sold": an announced deal that
was later called off still tells us the owner was willing, which is
what a sourcing model needs to predict. Episodes that only ever
reached a termination notice are excluded as ambiguous rather than
counted either way.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

CONTROL_KEYS = ["实际控制人变更", "控制权变更", "控股股东变更",
                "控股股东发生变更", "控股股东拟变更", "控制权"]

_CORE = re.compile("实际控制人|控制权|控股股东")
_CHANGE = re.compile("变更|易主|变动|转让|收购|要约|拍卖|划转|继承|认定|过户")
# '部分公司股份' must not be caught by '分公司', hence the lookbehind.
_EXCLUDE = re.compile("子公司|孙公司|(?<!部)分公司|少数股东|参股|会议地点|变更名称|"
                      "名称变更|更名|注册资本|经营范围|住所|办公地址|证券简称|"
                      "内部控制|内控制度")
_CONFIRMED = re.compile("发生变更|完成|已变更|过户|变更的公告|变更的提示")


@dataclass
class Episode:
    code: str
    name: str
    first_date: dt.date
    last_date: dt.date
    n_announcements: int
    first_title: str
    confirmed: bool
    terminated: bool


def is_control_change_title(title: str) -> bool:
    return bool(_CORE.search(title) and _CHANGE.search(title)
                and not _EXCLUDE.search(title))


def fetch_announcements(session, years: list[int],
                        keys: list[str] = CONTROL_KEYS) -> list[dict]:
    """Every announcement whose title matches one of the keys, for the
    given years. About four minutes for four years and six keys."""
    from ma_engine.adapters.ashare_annual import cninfo_search

    seen: set = set()
    out: list[dict] = []
    for y in years:
        for k in keys:
            for a in cninfo_search(session, k, f"{y}-01-01~{y}-12-31"):
                if a["id"] not in seen:
                    seen.add(a["id"])
                    out.append(a)
    return out


def build_episodes(announcements: list[dict], gap_days: int = 270) -> list[Episode]:
    """Group a company's control-change announcements into episodes. A
    gap of more than `gap_days` between announcements starts a new one."""
    by_code: dict[str, list[dict]] = defaultdict(list)
    for a in announcements:
        if is_control_change_title(a["title"]):
            by_code[a["code"]].append(a)

    episodes: list[Episode] = []
    for code, rows in by_code.items():
        rows.sort(key=lambda r: r["date"])
        current: list[dict] = []
        prev: dt.date | None = None
        for r in rows:
            d = dt.date.fromisoformat(r["date"])
            if prev is not None and (d - prev).days > gap_days:
                episodes.append(_episode(code, current))
                current = []
            current.append(r)
            prev = d
        if current:
            episodes.append(_episode(code, current))
    episodes.sort(key=lambda e: (e.first_date, e.code))
    return episodes


def _episode(code: str, rows: list[dict]) -> Episode:
    titles = [r["title"] for r in rows]
    return Episode(
        code=code, name=rows[0]["name"],
        first_date=dt.date.fromisoformat(rows[0]["date"]),
        last_date=dt.date.fromisoformat(rows[-1]["date"]),
        n_announcements=len(rows), first_title=titles[0],
        confirmed=any(_CONFIRMED.search(t) for t in titles),
        terminated=any("终止" in t for t in titles),
    )


def write_episodes(episodes: list[Episode], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "first_date", "last_date", "n_announcements",
                    "first_title", "confirmed", "terminated"])
        for e in episodes:
            w.writerow([e.code, e.name, e.first_date, e.last_date, e.n_announcements,
                        e.first_title, int(e.confirmed), int(e.terminated)])
    return path


def read_episodes(path: str | Path) -> list[Episode]:
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            out.append(Episode(
                code=r["code"].zfill(6), name=r.get("name", ""),
                first_date=dt.date.fromisoformat(r["first_date"][:10]),
                last_date=dt.date.fromisoformat(r["last_date"][:10]),
                n_announcements=int(r.get("n_announcements") or r.get("n_ann") or 1),
                first_title=r.get("first_title", ""),
                confirmed=str(r.get("confirmed")).lower() in ("1", "true"),
                terminated=str(r.get("terminated")).lower() in ("1", "true"),
            ))
    return out


@dataclass
class LabelSet:
    labels: dict[str, int]          # code -> 0/1
    excluded: dict[str, str]        # code -> reason
    window_start: dt.date
    window_end: dt.date

    @property
    def positives(self) -> int:
        return sum(self.labels.values())


def make_labels(episodes: list[Episode], population: list[str],
                window_start: dt.date, window_end: dt.date,
                in_progress_days: int = 180) -> LabelSet:
    """Label a population for one outcome window.

    1: an episode was first announced inside the window and was not
       only a termination.
    0: no episode touched the window.
    Excluded: a deal was already in progress at the scoring date (its
    last announcement fell within `in_progress_days` before the window),
    or the only episode in the window ended in termination.
    """
    by_code: dict[str, list[Episode]] = defaultdict(list)
    for e in episodes:
        by_code[e.code].append(e)

    labels: dict[str, int] = {}
    excluded: dict[str, str] = {}
    lookback = window_start - dt.timedelta(days=in_progress_days)
    for code in population:
        code = str(code).zfill(6)
        eps = by_code.get(code, [])
        in_window = [e for e in eps if window_start <= e.first_date <= window_end]
        pending = [e for e in eps if e.first_date < window_start
                   and e.last_date >= lookback]
        if pending:
            excluded[code] = "deal already in progress at the scoring date"
            continue
        if not in_window:
            labels[code] = 0
            continue
        if all(e.terminated and not e.confirmed for e in in_window):
            excluded[code] = "only a terminated deal in the window"
            continue
        labels[code] = 1
    return LabelSet(labels=labels, excluded=excluded,
                    window_start=window_start, window_end=window_end)


def write_labels(label_set: LabelSet, path: str | Path,
                 source_prefix: str = "ashare:") -> Path:
    """Write the labels file that `ma-engine evaluate` and `tune` read."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["company", "sold"])
        for code, y in sorted(label_set.labels.items()):
            w.writerow([f"{source_prefix}{code}", y])
    return path
