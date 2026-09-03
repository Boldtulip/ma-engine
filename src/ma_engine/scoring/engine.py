"""The scoring engine.

It runs the signals enabled in the scoring config, combines them into
one score from 0 to 100, and keeps every reason, so each score can be
read back as a short list of checkable sentences. A signal only moves
the score as far as its confidence allows, and missing data pulls a
score down rather than up: the engine would rather under-rank a
company than invent certainty.

The config decides which signals run and with what parameters. The
bundled config is the China succession example. Set
MA_ENGINE_SCORING_CONFIG to use your own.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from ma_engine.adapters.base import Company
from ma_engine.signals import Signal, compute

DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"


@dataclass
class ScoreReport:
    company: Company
    total: float                 # 0-100
    signals: list[Signal] = field(default_factory=list)
    contributions: dict[str, float] = field(default_factory=dict)

    def explain(self) -> str:
        """The score as plain sentences, strongest driver first."""
        lines = [f"{self.company.name}, succession score {self.total:.0f}/100"]
        order = sorted(self.signals, key=lambda s: -self.contributions.get(s.key, 0))
        for s in order:
            pts = self.contributions.get(s.key, 0.0)
            lines.append(f"  [{pts:+.1f}] {s.reason}")
        return "\n".join(lines)


def _config_path(path: Path | str | None) -> str:
    if path:
        return str(path)
    return os.environ.get("MA_ENGINE_SCORING_CONFIG") or str(DEFAULT_CONFIG)


@lru_cache(maxsize=8)
def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    if not config.get("signals"):
        raise ValueError(f"{path} enables no signals under `signals:`")
    return config


def load_config(path: Path | str | None = None) -> dict:
    """Read the scoring config (cached)."""
    return _load(_config_path(path))


def score_company(company: Company, config: dict | None = None) -> ScoreReport:
    config = config or load_config()
    signals = compute(company, config)

    weights = {k: float((v or {}).get("weight", 0.0))
               for k, v in config["signals"].items()}
    total_weight = sum(weights.values()) or 1.0
    contributions: dict[str, float] = {}
    for s in signals:
        w = weights.get(s.key, 0.0)
        contributions[s.key] = round(100 * (s.score * s.confidence * w) / total_weight, 1)

    total = round(sum(contributions.values()), 1)
    return ScoreReport(company=company, total=total, signals=signals,
                       contributions=contributions)


def rank(companies: list[Company], config: dict | None = None) -> list[ScoreReport]:
    config = config or load_config()
    reports = [score_company(c, config) for c in companies]
    return sorted(reports, key=lambda r: -r.total)
