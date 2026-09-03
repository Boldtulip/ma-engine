"""Succession signals.

Each signal looks at one aspect of a company and returns a score
between 0 and 1, together with a plain-sentence reason. The scoring
engine combines them with weights from scoring/weights.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass

from succession_radar.adapters.base import Company


@dataclass
class Signal:
    key: str          # machine name, e.g. "founder_age"
    score: float      # 0 (no succession pressure) to 1 (maximum pressure)
    confidence: float # 0 to 1, how much we trust this reading
    reason: str       # one plain sentence a person can check


def compute_all(company: Company) -> list[Signal]:
    """Run every signal on one company."""
    from succession_radar.signals import age, heirs, pressure, tenure

    return [
        age.founder_age_signal(company),
        tenure.tenure_signal(company),
        heirs.heir_absence_signal(company),
        pressure.sell_pressure_signal(company),
    ]
