"""Founder age: the strongest succession signal.

Chinese registries do not publish the age of private-company owners.
When an exact age is disclosed (listed companies), we use it. When it
is not, we estimate a birth cohort from the owner's given name.
Given names in China follow strong generational fashions: a founder
named 建国 was almost certainly born around 1950, one named 子轩
around 2005. The bundled table is a small demonstration subset; for
production use, load the full ChineseNames database (Bao et al.,
1930-2008, built on official records of 1.2 billion people).
"""

from __future__ import annotations

import csv
import datetime
from pathlib import Path
from typing import Optional

from ma_engine.adapters.base import Company
from ma_engine.signals import Signal

# Common two-character (compound) surnames, needed to split full names.
COMPOUND_SURNAMES = {
    "欧阳", "司马", "上官", "诸葛", "东方", "皇甫", "尉迟", "公孙",
    "慕容", "夏侯", "令狐", "宇文", "长孙", "端木", "司徒", "申屠",
}

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
    """Describe a peak year the way a person would say it: '1950s' when
    the table holds a round decade, 'the mid-1950s' when it holds a
    mid-decade year."""
    return f"the {peak}s" if peak % 10 == 0 else f"the mid-{peak - 5}s"


def estimate_age(full_name: str, year: Optional[int] = None) -> tuple[Optional[int], float, str]:
    """Return (estimated age, confidence, method).

    Confidence is low by design: a name narrows the birth decade,
    it does not prove it.
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


# Owner age mapped to the chance that the company actually changes
# hands. The curve rises through the fifties, peaks between about 63
# and 72, and then falls away.
#
# The falling tail is deliberate. An
# owner still in the chair at 82 has spent twenty years demonstrating
# that he does not intend to sell, and by that age control has usually
# been arranged inside the family or the company already. He is the
# least persuadable seller on the list, not the most. The owner in his
# sixties is the one at the decision point: past the statutory
# retirement age, still in good health, with a business that is still
# straightforward to sell.
#
# The anchors are judgment, not measurement. Calibrate them against
# your own record of which companies actually sold.
AGE_CURVE = [
    (40, 0.02),
    (50, 0.10),
    (55, 0.30),
    (58, 0.50),
    (60, 0.75),
    (63, 0.95),   # statutory retirement age for men after the 2024 reform
    (66, 1.00),
    (72, 1.00),   # the decision window closes around here
    (75, 0.85),
    (80, 0.60),
    (85, 0.45),
    (95, 0.40),
]


def _age_to_score(age: int) -> float:
    """Interpolate the curve above."""
    if age <= AGE_CURVE[0][0]:
        return AGE_CURVE[0][1]
    if age >= AGE_CURVE[-1][0]:
        return AGE_CURVE[-1][1]
    for (x0, y0), (x1, y1) in zip(AGE_CURVE, AGE_CURVE[1:]):
        if x0 <= age <= x1:
            return round(y0 + (y1 - y0) * (age - x0) / (x1 - x0), 3)
    return 0.0


def founder_age_signal(company: Company) -> Signal:
    owner = company.controller()
    if owner is None:
        return Signal("founder_age", 0.0, 0.0, "No individual owner found in the records.")

    if owner.age is not None:
        return Signal(
            "founder_age",
            _age_to_score(owner.age),
            0.95,
            f"{owner.name} is {owner.age} years old (disclosed).",
        )

    est, conf, method = estimate_age(owner.name)
    if est is None:
        return Signal("founder_age", 0.0, 0.0,
                      f"Age of {owner.name} is unknown and the name gives no cohort hint.")
    return Signal(
        "founder_age",
        _age_to_score(est),
        conf,
        f"{owner.name} is estimated around {est} years old ({method}).",
    )
