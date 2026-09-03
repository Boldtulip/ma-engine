"""Owner tenure: how long the same person has run the company.

A legal representative unchanged since a founding thirty years ago
means the founder still runs the business — and puts a floor under
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

from succession_radar.adapters.base import Company
from succession_radar.signals import Signal


def _score(years: int) -> float:
    # Under 10 years: little signal. 10 to 30: rising. 30+: maximum.
    if years < 10:
        return 0.05
    if years >= 30:
        return 1.0
    return round((years - 10) / 20, 2)


def tenure_signal(company: Company) -> Signal:
    year = datetime.date.today().year
    if not company.legal_rep:
        return Signal("owner_tenure", 0.0, 0.0, "No named owner in the records.")

    if company.legal_rep_since:
        years = year - company.legal_rep_since
        return Signal(
            "owner_tenure", _score(years), 0.9,
            f"{company.legal_rep} has held the role for {years} years "
            f"(since {company.legal_rep_since}).",
        )

    if company.founded_year:
        years = year - company.founded_year
        # A founding date is only a ceiling on tenure, never a measure
        # of it, so this reads at roughly half the weight of a known
        # start date.
        return Signal(
            "owner_tenure", _score(years), 0.45,
            f"The company is {years} years old (founded "
            f"{company.founded_year}) and the date {company.legal_rep} took "
            f"the role is not on record, so long tenure is possible but "
            f"unconfirmed.",
        )

    return Signal("owner_tenure", 0.0, 0.0, "No tenure information in the records.")
