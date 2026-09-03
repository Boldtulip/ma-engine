"""Owner tenure: how long the same person has run the company.

A legal representative unchanged since a founding thirty years ago
means the founder still runs the business — and puts a floor under
their age even when the age itself is unknown. Change records
(变更记录) are public in China, so this signal is fully computable
for private companies.
"""

from __future__ import annotations

import datetime

from succession_radar.adapters.base import Company
from succession_radar.signals import Signal


def tenure_signal(company: Company) -> Signal:
    year = datetime.date.today().year
    since = company.legal_rep_since or company.founded_year
    if since is None or not company.legal_rep:
        return Signal("owner_tenure", 0.0, 0.0, "No tenure information in the records.")

    years = year - since
    # Under 10 years: little signal. 10 to 30 years: rising. 30+: maximum.
    if years < 10:
        score = 0.05
    elif years >= 30:
        score = 1.0
    else:
        score = round((years - 10) / 20, 2)

    founded = f" (company founded {company.founded_year})" if company.founded_year else ""
    return Signal(
        "owner_tenure",
        score,
        0.9,
        f"{company.legal_rep} has been legal representative for {years} years{founded}.",
    )
