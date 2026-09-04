"""Evaluate a scoring config against known outcomes, and tune it.

The score is a weighted sum of signals, and each signal maps one
feature through a curve or a threshold. Treat those weights, curve
points and thresholds as hyperparameters and the engine becomes a
small additive model that can be fitted to a record of which
companies actually sold. This module does that fitting.

What you need: a CSV of labels with two columns, `company` (the
company name, or its `source` id such as `ashare:000001`) and `sold`
(1 if the company changed hands in the period you care about, 0 if
not). That record is yours; nothing in the repository provides it.

Evaluation needs no extra packages. Tuning uses Optuna, installed with
`pip install -e ".[tune]"`.
"""

from __future__ import annotations

import copy
import csv
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ma_engine.adapters.base import Company
from ma_engine.scoring.engine import score_company


# --- labels ---------------------------------------------------------------

def read_labels(path: str | Path) -> dict[str, int]:
    """Read `company,sold` rows. Keys are whatever the file uses to name
    a company; matching against Company records tries `source` first,
    then `name`."""
    labels: dict[str, int] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "company" not in reader.fieldnames \
                or "sold" not in reader.fieldnames:
            raise ValueError(f"{path} needs the columns `company` and `sold`")
        for row in reader:
            key = (row.get("company") or "").strip()
            if key:
                labels[key] = 1 if str(row.get("sold")).strip() in ("1", "true", "True", "yes") else 0
    return labels


def match_labels(companies: list[Company], labels: dict[str, int]
                 ) -> list[tuple[Company, int]]:
    out = []
    for c in companies:
        if c.source in labels:
            out.append((c, labels[c.source]))
        elif c.name in labels:
            out.append((c, labels[c.name]))
    return out


# --- metrics --------------------------------------------------------------

def auc(scores: list[float], labels: list[int]) -> float:
    """Area under the ROC curve, computed as the probability that a
    random positive outscores a random negative (ties count half).
    No dependencies, fine for a few thousand companies."""
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return float("nan")
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else (0.5 if p == n else 0.0)
    return wins / (len(pos) * len(neg))


def precision_at_k(scores: list[float], labels: list[int], k: int) -> float:
    """Share of positives among the k highest-scoring companies."""
    order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
    return sum(labels[i] for i in order) / max(len(order), 1)


def lift_at_k(scores: list[float], labels: list[int], k: int) -> float:
    """Precision in the top k divided by the base rate: how many times
    more often a sale appears at the top of the list than at random."""
    base = sum(labels) / max(len(labels), 1)
    return precision_at_k(scores, labels, k) / base if base else float("nan")


@dataclass
class Evaluation:
    n: int
    positives: int
    auc: float
    precision_at_k: float
    lift_at_k: float
    k: int

    def __str__(self) -> str:
        return (f"{self.n} labelled companies, {self.positives} sold "
                f"({self.positives / max(self.n, 1):.1%})\n"
                f"AUC {self.auc:.3f}   precision@{self.k} {self.precision_at_k:.1%}   "
                f"lift@{self.k} {self.lift_at_k:.2f}x")


def evaluate(pairs: list[tuple[Company, int]], config: dict, k: int = 50
             ) -> Evaluation:
    scores = [score_company(c, config).total for c, _ in pairs]
    labels = [y for _, y in pairs]
    k = min(k, len(pairs))
    return Evaluation(
        n=len(pairs), positives=sum(labels),
        auc=auc(scores, labels),
        precision_at_k=precision_at_k(scores, labels, k),
        lift_at_k=lift_at_k(scores, labels, k), k=k,
    )


# --- search space ---------------------------------------------------------

def _is_curve(value) -> bool:
    return (isinstance(value, list) and value
            and all(isinstance(pt, (list, tuple)) and len(pt) == 2 for pt in value))


def suggest_config(trial, base: dict) -> dict:
    """Build a candidate config from an Optuna trial.

    Every signal's weight is searched in [0, 1]. Inside a signal, a
    curve keeps its x points and searches each y in [0, 1]; any other
    number is searched between half and double its default (bounded to
    [0, 1] for values that are confidences or weights). Non-numeric
    parameters are left alone.
    """
    cfg = copy.deepcopy(base)
    for key, params in (cfg.get("signals") or {}).items():
        params = params if params is not None else {}
        cfg["signals"][key] = params
        params["weight"] = trial.suggest_float(f"{key}.weight", 0.0, 1.0)
        for name, value in list(params.items()):
            if name == "weight":
                continue
            if _is_curve(value):
                params[name] = [[x, trial.suggest_float(f"{key}.{name}[{x}]", 0.0, 1.0)]
                                for x, _ in value]
            elif isinstance(value, bool):
                continue
            elif isinstance(value, int):
                lo, hi = max(1, value // 2), max(2, value * 2)
                params[name] = trial.suggest_int(f"{key}.{name}", lo, hi)
            elif isinstance(value, float):
                if 0.0 <= value <= 1.0 and ("confidence" in name or "weight" in name):
                    params[name] = trial.suggest_float(f"{key}.{name}", 0.0, 1.0)
                else:
                    params[name] = trial.suggest_float(f"{key}.{name}", value / 2, value * 2)
    return cfg


# --- tuning ---------------------------------------------------------------

def _folds(n: int, k: int, seed: int) -> list[list[int]]:
    idx = list(range(n))
    random.Random(seed).shuffle(idx)
    return [idx[i::k] for i in range(k)]


def tune(pairs: list[tuple[Company, int]], base: dict, trials: int = 100,
         folds: int = 5, k: int = 50, seed: int = 0,
         log: Callable[[str], None] | None = None) -> tuple[dict, float, float]:
    """Search the config's hyperparameters to maximise held-out AUC.

    Returns (best config, baseline AUC, tuned AUC), both AUCs measured
    the same way: the mean over folds of the AUC on the held-out fold.
    The objective is cross-validated so the tuned config is judged on
    companies it was not fitted to.
    """
    try:
        import optuna
    except ImportError as exc:
        raise ImportError("Tuning needs Optuna: pip install -e '.[tune]'") from exc

    n = len(pairs)
    if n < 20 or sum(y for _, y in pairs) < 5:
        raise ValueError("Need at least 20 labelled companies and 5 sales to tune.")
    folds = max(2, min(folds, n // 10))
    split = _folds(n, folds, seed)

    def cv_auc(config: dict) -> float:
        vals = []
        for held in split:
            sub = [pairs[i] for i in held]
            scores = [score_company(c, config).total for c, _ in sub]
            a = auc(scores, [y for _, y in sub])
            if a == a:  # skip folds with a single class
                vals.append(a)
        return sum(vals) / len(vals) if vals else 0.0

    baseline = cv_auc(base)

    def objective(trial):
        return cv_auc(suggest_config(trial, base))

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize",
                                sampler=optuna.samplers.TPESampler(seed=seed))
    study.enqueue_trial({})  # let the first trial be whatever the sampler picks
    for i in range(trials):
        study.optimize(objective, n_trials=1)
        if log and (i + 1) % max(trials // 10, 1) == 0:
            log(f"  trial {i + 1}/{trials}: best held-out AUC so far {study.best_value:.3f}")

    best = suggest_config(optuna.trial.FixedTrial(study.best_params), base)
    return best, baseline, study.best_value


def write_config(config: dict, path: str | Path) -> Path:
    import yaml

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ("# Scoring config produced by `ma-engine tune`.\n"
              "# Weights and curve points were fitted to a labelled set of\n"
              "# outcomes; see the tune command's report for the metrics.\n\n")
    path.write_text(header + yaml.safe_dump(config, allow_unicode=True,
                                            sort_keys=False), encoding="utf-8")
    return path
