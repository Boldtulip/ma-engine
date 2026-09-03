"""Owner age: in the China example, the strongest signal.

Chinese registries do not publish the age of private-company owners.
When an exact age is disclosed (listed companies), it is used. When it
is not, a birth cohort is estimated from the owner's given name.
Given names in China follow strong generational fashions: a founder
named 建国 was almost certainly born around 1950, one named 子轩
around 2005. The bundled table is a small demonstration subset; for
serious use, load the full ChineseNames database (Bao et al.,
1930-2008, built on official records of 1.2 billion people).

The mapping from age to score is a curve of (age, value) points in
the scoring config. See config.yaml for the reasoning behind its shape.
"""

from __future__ import annotations

import csv
import datetime
from pathlib import Path
from typing import Optional

from ma_engine.adapters.base import Company
from ma_engine.signals import Signal, signal

# Common two-character (compound) surnames, needed to split full names.
COMPOUND_SURNAMES = {
    "欧阳", "司马", "上官", "诸葛", "东方", "皇甫", "尉迟", "公孙",
    "慕容", "夏侯", "令狐", "宇文", "长孙", "端木", "司徒", "申屠",
}

# Used when the config gives no curve. Same shape as config.yaml.
DEFAULT_CURVE = [
    (40, 0.02), (50, 0.10), (55, 0.30), (58, 0.50), (60, 0.75),
    (63, 0.95), (66, 1.00), (72, 1.00), (75, 0.85), (80, 0.60),
    (85, 0.45), (95, 0.40),
]

_COHORTS: dict[str, int] = {}


def _load_cohorts() -> dict[str, int]:
    global _COHORTS
    if not _COHORTS:
        path = Path(__file__).parent / "name_cohorts.csv"
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                _COHORTS[row["given_name"]] = int(row["peak_decade"])
    return _COHORTS


def split_name(full_name: str) -> tuple[str, str]:
    """Split a Chinese full name into (surname, given name)."""
    if len(full_name) >= 3 and full_name[:2] in COMPOUND_SURNAMES:
        return full_name[:2], full_name[2:]
    return full_name[:1], full_name[1:]


def _cohort_phrase(peak: int) -> str:
    """'the 1950s' for a round decade, 'the mid-1950s' for a mid-decade year."""
    return f"the {peak}s" if peak % 10 == 0 else f"the mid-{peak - 5}s"


def estimate_age(full_name: str, year: Optional[int] = None) -> tuple[Optional[int], float, str]:
    """Return (estimated age, confidence, method).

    Confidence is low by design: a name narrows the birth decade, it
    does not prove it.
    """
    year = year or datetime.date.today().year
    cohorts = _load_cohorts()
    _, given = split_name(full_name)
    if not given:
        return None, 0.0, "no given name"

    if given in cohorts:
        birth = cohorts[given] + 5  # middle of the decade
        return (year - birth, 0.55,
                f"given name '{given}' peaks in {_cohort_phrase(cohorts[given])}")

    # Fall back to single characters inside the given name.
    for ch in given:
        if ch in cohorts:
            birth = cohorts[ch] + 5
            return (year - birth, 0.35,
                    f"name character '{ch}' peaks in "
                    f"{_cohort_phrase(cohorts[ch])}")

    return None, 0.0, "name not in cohort table"


def _age_to_score(age: int, curve: list | None = None) -> float:
    """Interpolate the age curve."""
    pts = [(float(a), float(v)) for a, v in (curve or DEFAULT_CURVE)]
    if age <= pts[0][0]:
        return pts[0][1]
    if age >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= age <= x1:
            return round(y0 + (y1 - y0) * (age - x0) / (x1 - x0), 3)
    return 0.0


@signal("founder_age")
def founder_age_signal(company: Company, params: dict | None = None) -> Signal:
    params = params or {}
    curve = params.get("curve")
    disclosed_conf = float(params.get("disclosed_confidence", 0.95))

    owner = company.controller()
    if owner is None:
        return Signal("founder_age", 0.0, 0.0, "No individual owner found in the records.")

    if owner.age is not None:
        return Signal(
            "founder_age",
            _age_to_score(owner.age, curve),
            disclosed_conf,
            f"{owner.name} is {owner.age} years old (disclosed).",
        )

    est, conf, method = estimate_age(owner.name)
    if est is None:
        return Signal("founder_age", 0.0, 0.0,
                      f"Age of {owner.name} is unknown and the name gives no cohort hint.")
    return Signal(
        "founder_age",
        _age_to_score(est, curve),
        conf,
        f"{owner.name} is estimated around {est} years old ({method}).",
    )
