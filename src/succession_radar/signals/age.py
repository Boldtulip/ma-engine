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

from succession_radar.adapters.base import Company
from succession_radar.signals import Signal

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
        return year - birth, 0.55, f"given name '{given}' peaks in the {cohorts[given]}s"

    # Fall back to single characters inside the given name.
    for ch in given:
        if ch in cohorts:
            birth = cohorts[ch] + 5
            return year - birth, 0.35, f"name character '{ch}' peaks in the {cohorts[ch]}s"

    return None, 0.0, "name not in cohort table"


def _age_to_score(age: int) -> float:
    """Map owner age to succession pressure. Below 50 there is little
    pressure; from 55 it rises; past 70 it is close to certain."""
    if age < 50:
        return 0.05
    if age >= 70:
        return 1.0
    return round((age - 50) / 20, 2)  # linear ramp 50 -> 70


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
