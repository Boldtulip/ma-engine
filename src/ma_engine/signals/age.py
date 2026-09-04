"""Owner age.

Where the records disclose an age, it is used. Where they do not, an
age is not guessed: a lower bound is derived from the company's own
records instead. Somebody who has been the legal representative since
the company was founded thirty years ago was old enough to found a
company then, so they are at least thirty years older than that now.
The bound is stated as a bound in the output, and carries lower
confidence than a disclosed age.

The mapping from age to score is a curve of (age, value) points in the
scoring config. See config.yaml for the reasoning behind its shape.
"""

from __future__ import annotations

import datetime
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

# Nobody founds or takes charge of a company much younger than this, so
# years in the role plus this number is a floor on the person's age.
DEFAULT_MIN_AGE_AT_APPOINTMENT = 30


def split_name(full_name: str) -> tuple[str, str]:
    """Split a Chinese full name into (surname, given name)."""
    if len(full_name) >= 3 and full_name[:2] in COMPOUND_SURNAMES:
        return full_name[:2], full_name[2:]
    return full_name[:1], full_name[1:]


def age_floor(company: Company, min_age_at_appointment: int,
              year: Optional[int] = None) -> tuple[Optional[int], Optional[int]]:
    """A lower bound on the owner's age, and the year it is counted from.

    Uses the year the current legal representative took the role. Where
    that is not recorded, the founding year is used, which is weaker:
    the company may be on its third chairman.
    """
    year = year or datetime.date.today().year
    since = company.legal_rep_since or company.founded_year
    if not since or since > year:
        return None, None
    return min_age_at_appointment + (year - since), since


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
    floor_conf = float(params.get("age_floor_confidence", 0.5))
    min_age = int(params.get("min_age_at_appointment",
                             DEFAULT_MIN_AGE_AT_APPOINTMENT))

    owner = company.controller()
    if owner is None:
        return Signal("founder_age", 0.0, 0.0,
                      "No individual owner found in the records.")

    if owner.age is not None:
        return Signal("founder_age", _age_to_score(owner.age, curve),
                      disclosed_conf,
                      f"{owner.name} is {owner.age} years old (disclosed).")

    floor, since = age_floor(company, min_age)
    if floor is None:
        return Signal("founder_age", 0.0, 0.0,
                      f"No age on record for {owner.name}, and no start date "
                      f"to put a bound on it.")

    known_start = company.legal_rep_since is not None
    source = (f"has held the role since {since}" if known_start
              else f"has been on record since the company was founded in {since}")
    # A bound cannot be pushed through the falling side of the curve
    # honestly: the owner may be well past the peak. Score it at the
    # bound and let the lower confidence carry the uncertainty.
    return Signal(
        "founder_age", _age_to_score(floor, curve),
        floor_conf if known_start else floor_conf * 0.6,
        f"No age on record for {owner.name}, who {source}, so is at "
        f"least about {floor}.",
    )
