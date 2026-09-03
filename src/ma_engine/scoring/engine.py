"""The scoring engine.

It combines the signals into one succession score from 0 to 100 and
keeps every reason, so each score can be read back as a short list of
checkable sentences. A signal only moves the score as far as its
confidence allows: an age estimated from a name counts for about half
of a disclosed age. Missing data pulls a score down, never up — the
engine prefers to under-rank a company than to invent certainty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ma_engine.adapters.base import Company
from ma_engine.signals import Signal, compute_all

DEFAULT_WEIGHTS = Path(__file__).parent / "weights.yaml"


@dataclass
class ScoreReport:
    company: Company
    total: float                 # 0-100
    signals: list[Signal] = field(default_factory=list)
    contributions: dict[str, float] = field(default_factory=dict)

    def explain(self) -> str:
        """The score as plain sentences, strongest driver first."""
        lines = [f"{self.company.name} — succession score {self.total:.0f}/100"]
        order = sorted(self.signals, key=lambda s: -self.contributions.get(s.key, 0))
        for s in order:
            pts = self.contributions.get(s.key, 0.0)
            lines.append(f"  [{pts:+.1f}] {s.reason}")
        return "\n".join(lines)


def load_weights(path: Path | str = DEFAULT_WEIGHTS) -> dict[str, float]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["weights"]


def score_company(company: Company, weights: dict[str, float] | None = None) -> ScoreReport:
    weights = weights or load_weights()
    signals = compute_all(company)

    total_weight = sum(weights.values()) or 1.0
    contributions: dict[str, float] = {}
    for s in signals:
        w = weights.get(s.key, 0.0)
        contributions[s.key] = round(100 * (s.score * s.confidence * w) / total_weight, 1)

    total = round(sum(contributions.values()), 1)
    return ScoreReport(company=company, total=total, signals=signals,
                       contributions=contributions)


def rank(companies: list[Company], weights: dict[str, float] | None = None) -> list[ScoreReport]:
    weights = weights or load_weights()
    reports = [score_company(c, weights) for c in companies]
    return sorted(reports, key=lambda r: -r.total)
