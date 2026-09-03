"""Owner tenure: how long the same person has run the company.

A legal representative unchanged since a founding thirty years ago
means the founder still runs the business, and it puts a floor under
their age even when the age itself is unknown. Change records
(变更记录) are public in China, so this signal is computable.

Two cases must not be confused. When the records say when the current
holder took the role, the tenure is a fact. When they do not, the
founding year is only a proxy, and a weak one: a listed company
founded in 1992 may be on its third chairman. The proxy is used, but
at reduced confidence and with wording that says what it is.
"""

from __future__ import annotations

import datetime

from ma_engine.adapters.base import Company
from ma_engine.signals import Signal, signal


def _score(years: int, lo: int, hi: int) -> float:
    """Below `lo` years: little signal. `lo` to `hi`: rising. Above `hi`: maximum."""
    if years < lo:
        return 0.05
    if years >= hi:
        return 1.0
    return round((years - lo) / max(hi - lo, 1), 2)


@signal("owner_tenure")
def tenure_signal(company: Company, params: dict | None = None) -> Signal:
    params = params or {}
    lo = int(params.get("years_for_minimum", 10))
    hi = int(params.get("years_for_maximum", 30))
    known_conf = float(params.get("known_date_confidence", 0.9))
    founding_conf = float(params.get("founding_year_confidence", 0.45))

    year = datetime.date.today().year
    if not company.legal_rep:
        return Signal("owner_tenure", 0.0, 0.0, "No named owner in the records.")

    if company.legal_rep_since:
        years = year - company.legal_rep_since
        return Signal(
            "owner_tenure", _score(years, lo, hi), known_conf,
            f"{company.legal_rep} has held the role for {years} years "
            f"(since {company.legal_rep_since}).",
        )

    if company.founded_year:
        years = year - company.founded_year
        return Signal(
            "owner_tenure", _score(years, lo, hi), founding_conf,
            f"The company is {years} years old (founded "
            f"{company.founded_year}) and the date {company.legal_rep} took "
            f"the role is not on record, so long tenure is possible but "
            f"unconfirmed.",
        )

    return Signal("owner_tenure", 0.0, 0.0, "No tenure information in the records.")
