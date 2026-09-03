"""CSV adapter: load companies from a flat file.

Expected columns (only `name` is required):
name, industry, region, founded_year, legal_rep, legal_rep_since,
revenue_m, net_profit_m, pledge_ratio, litigation_count,
shareholders (like "王建国:70;王磊:30"), executives (like "王建国:执行董事")
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from ma_engine.adapters.base import Adapter, Company, Person


def _parse_people(cell: str, pct: bool) -> list[Person]:
    people = []
    for part in (cell or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            name, extra = part.split(":", 1)
            if pct:
                people.append(Person(name.strip(), "股东", float(extra)))
            else:
                people.append(Person(name.strip(), extra.strip()))
        else:
            people.append(Person(part))
    return people


def _opt_int(v: str) -> int | None:
    return int(float(v)) if v not in (None, "",) else None


def _opt_float(v: str, default: float = 0.0) -> float:
    return float(v) if v not in (None, "") else default


class CsvAdapter(Adapter):
    name = "csv"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def companies(self) -> Iterable[Company]:
        with open(self.path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                yield Company(
                    name=row["name"],
                    industry=row.get("industry", ""),
                    region=row.get("region", ""),
                    founded_year=_opt_int(row.get("founded_year", "")),
                    legal_rep=row.get("legal_rep", ""),
                    legal_rep_since=_opt_int(row.get("legal_rep_since", "")),
                    shareholders=_parse_people(row.get("shareholders", ""), pct=True),
                    executives=_parse_people(row.get("executives", ""), pct=False),
                    revenue_m=_opt_float(row.get("revenue_m", "")) or None,
                    net_profit_m=_opt_float(row.get("net_profit_m", "")) or None,
                    pledge_ratio=_opt_float(row.get("pledge_ratio", "")),
                    litigation_count=int(_opt_float(row.get("litigation_count", ""))),
                    source=f"csv:{self.path.name}",
                )
