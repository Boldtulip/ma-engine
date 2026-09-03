"""Sell pressure: signs that the owner may need or want liquidity.

Two public signals are used: pledged equity (股权出质 is public in the
registry; a pledged majority stake means the owner borrowed against
the company) and published litigation. Both raise the chance that an
owner near retirement chooses to sell rather than hold on.
"""

from __future__ import annotations

from ma_engine.adapters.base import Company
from ma_engine.signals import Signal


def sell_pressure_signal(company: Company) -> Signal:
    reasons: list[str] = []
    score = 0.0

    if company.pledge_ratio > 0:
        score += min(company.pledge_ratio, 1.0) * 0.7
        reasons.append(f"{company.pledge_ratio:.0%} of the controlling stake is pledged")

    if company.litigation_count > 0:
        score += min(company.litigation_count / 10, 1.0) * 0.3
        reasons.append(f"{company.litigation_count} published court case(s)")

    if not reasons:
        return Signal("sell_pressure", 0.0, 0.8,
                      "No equity pledges or published litigation on record.")

    return Signal("sell_pressure", round(min(score, 1.0), 2), 0.8,
                  "Signs of pressure: " + " and ".join(reasons) + ".")
