"""An example of adding your own signal.

This module is not part of the engine. It shows the whole recipe:
write a function that takes a Company and a dict of parameters and
returns a Signal, register it with @signal("name"), and then enable it
in a scoring config under `signals:` with the module listed under
`plugins:`. See examples/scoring_config.yaml.

The signal below is a generic one that works in any market: how much
of the company the owner holds. An owner with 100% can sell without
negotiating with partners; a fragmented cap table makes a sale slower
and less certain.
"""

from __future__ import annotations

from ma_engine.adapters.base import Company
from ma_engine.signals import Signal, signal


@signal("concentrated_ownership")
def concentrated_ownership(company: Company, params: dict | None = None) -> Signal:
    params = params or {}
    full_control_at = float(params.get("full_control_at_pct", 67))

    owner = company.controller()
    if owner is None or not owner.ownership_pct:
        return Signal("concentrated_ownership", 0.0, 0.0,
                      "No ownership percentage on record for the owner.")

    pct = owner.ownership_pct
    score = round(min(pct / full_control_at, 1.0), 2)
    return Signal(
        "concentrated_ownership", score, 0.8,
        f"{owner.name} holds {pct:.0f}% of the company"
        + (", enough to decide a sale alone." if pct >= full_control_at
           else ", so a sale needs the other holders."),
    )
