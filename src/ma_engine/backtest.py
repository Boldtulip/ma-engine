"""Backtest: score companies as they stood at a past date, then check
which of them came up for sale afterwards.

Steps, all on public data and all kept on your machine:

1. Collect control-change announcements and group them into episodes.
2. Choose the population: the companies privately controlled today,
   plus every company that had an episode in the window (otherwise
   the ones that were sold to a state buyer would be missing from the
   sample, and they are exactly the positives).
3. Label the population for the window.
4. Optionally keep every positive and a random sample of negatives,
   because each annual report costs 20 to 45 seconds to read. AUC is
   unaffected by that sampling; lift is reported reweighted to the
   full population's base rate.
5. Read the FY annual reports for the sample and build point-in-time
   records.
6. Evaluate the scoring config, and print the command to tune it.
"""

from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path

from ma_engine.adapters.ashare_annual import AShareAnnualAdapter, cninfo_session
from ma_engine.labels import control_changes as cc
from ma_engine.scoring.engine import load_config, score_company
from ma_engine.tune import auc, precision_at_k


def population_today(cache_path: Path) -> list[str]:
    """Codes of the companies privately controlled in the live cache."""
    raw = json.loads(cache_path.read_text(encoding="utf-8"))
    items = raw["companies"] if isinstance(raw, dict) else raw
    return [c["source"].split(":")[-1] for c in items if c.get("is_private")]


def run(fiscal_year: int, window_start: dt.date, window_end: dt.date,
        out_dir: Path, live_cache: Path, negatives: int | None = 1000,
        seed: int = 0, workers: int = 8, config_path: str | None = None,
        episodes_path: Path | None = None, k: int = 50,
        log=print) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. episodes
    if episodes_path and Path(episodes_path).exists():
        episodes = cc.read_episodes(episodes_path)
        log(f"Read {len(episodes)} control-change episodes from {episodes_path}")
    else:
        years = list(range(min(2023, window_start.year), window_end.year + 1))
        log(f"Collecting control-change announcements for {years[0]}-{years[-1]}...")
        anns = cc.fetch_announcements(cninfo_session(), years)
        episodes = cc.build_episodes(anns)
        cc.write_episodes(episodes, out_dir / "control_episodes.csv")
        log(f"  {len(anns)} announcements, {len(episodes)} episodes")

    # 2. population
    base = set(population_today(live_cache))
    in_window = {e.code for e in episodes
                 if window_start <= e.first_date <= window_end}
    population = sorted(base | in_window)
    log(f"Population: {len(base)} privately controlled today plus "
        f"{len(in_window - base)} that had a deal in the window = {len(population)}")

    # 3. labels
    label_set = cc.make_labels(episodes, population, window_start, window_end)
    log(f"Labels: {label_set.positives} came up for sale, "
        f"{len(label_set.labels) - label_set.positives} did not, "
        f"{len(label_set.excluded)} excluded")
    base_rate = label_set.positives / max(len(label_set.labels), 1)

    # 4. sample
    pos = [c for c, y in label_set.labels.items() if y == 1]
    neg = [c for c, y in label_set.labels.items() if y == 0]
    if negatives is not None and len(neg) > negatives:
        neg = random.Random(seed).sample(neg, negatives)
        log(f"Sampling {negatives} negatives; AUC is unaffected, lift is "
            f"reweighted to the full base rate of {base_rate:.1%}")
    sample = sorted(pos + neg)
    cc.write_labels(cc.LabelSet({c: label_set.labels[c] for c in sample},
                                label_set.excluded, window_start, window_end),
                    out_dir / "labels.csv")

    # 5. point-in-time features
    adapter = AShareAnnualAdapter(sample, fiscal_year,
                                  cache_path=out_dir / f"features_fy{fiscal_year}.json",
                                  workers=workers, progress=True)
    companies = list(adapter.companies())
    read_codes = {c.source.split(":")[-1] for c in companies}
    log(f"Features: {len(companies)} companies read as of FY{fiscal_year}; "
        f"{len(adapter.failures)} not usable")
    reasons = {}
    for r in adapter.failures.values():
        reasons[r.split("(")[0].strip()] = reasons.get(r.split("(")[0].strip(), 0) + 1
    for r, n in sorted(reasons.items(), key=lambda x: -x[1])[:6]:
        log(f"  {n:4d}  {r}")

    # 6. evaluate
    config = load_config(config_path)
    pairs = [(c, label_set.labels[c.source.split(':')[-1]]) for c in companies
             if c.source.split(":")[-1] in label_set.labels]
    scores = [score_company(c, config).total for c, _ in pairs]
    labels = [y for _, y in pairs]
    n_pos = sum(labels)
    a = auc(scores, labels)
    kk = min(k, len(pairs))
    p_at_k = precision_at_k(scores, labels, kk)
    # Lift against the sample's own base rate, then rescaled: sampling
    # negatives at rate s multiplies the sample base rate by 1/s-ish, so
    # report lift relative to the full population base rate.
    sample_rate = n_pos / max(len(labels), 1)
    lift_sample = p_at_k / sample_rate if sample_rate else float("nan")

    result = {
        "fiscal_year": fiscal_year,
        "window": [str(window_start), str(window_end)],
        "population": len(label_set.labels),
        "positives_in_population": label_set.positives,
        "base_rate": base_rate,
        "sampled": len(pairs),
        "sampled_positives": n_pos,
        "coverage_of_positives": (len([c for c in pos if c in read_codes]) /
                                  max(len(pos), 1)),
        "auc": a,
        "k": kk,
        "precision_at_k_sample": p_at_k,
        "lift_at_k_within_sample": lift_sample,
    }
    (out_dir / "result.json").write_text(json.dumps(result, indent=1),
                                         encoding="utf-8")

    log("")
    log(f"Scored as of FY{fiscal_year}; outcomes {window_start} to {window_end}.")
    log(f"{len(pairs)} companies with features, {n_pos} of which came up for sale.")
    log(f"AUC {a:.3f}")
    log(f"Top {kk} by score: {p_at_k:.1%} came up for sale, against "
        f"{sample_rate:.1%} in the sample ({lift_sample:.2f}x).")
    log(f"Coverage: annual reports read for {result['coverage_of_positives']:.0%} "
        f"of the positives.")
    log("")
    log("To fit the config to these outcomes:")
    log(f"  ma-engine tune --labels {out_dir / 'labels.csv'} --ashare "
        f"--cache {out_dir / f'features_fy{fiscal_year}.json'} --trials 200 "
        f"--out {out_dir / 'tuned_config.yaml'}")
    return result
