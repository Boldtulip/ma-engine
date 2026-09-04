"""Command line interface.

Three commands:
  ma-engine demo                 run the whole pipeline on bundled synthetic data
  ma-engine score --csv FILE     rank companies from your own CSV
  ma-engine dossier --name NAME  full dossier for one company (demo or CSV data)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ma_engine.adapters.base import Company
from ma_engine.adapters.csv_adapter import CsvAdapter
from ma_engine.adapters.dummy import DummyAdapter
from ma_engine.agent.dossier import build_dossier
from ma_engine.matching.matcher import match_buyers
from ma_engine.scoring.engine import rank


DEFAULT_CACHE = Path("data/ashare_scored.json")


def _load(args: argparse.Namespace) -> list[Company]:
    if getattr(args, "csv", None):
        return list(CsvAdapter(args.csv).companies())
    if getattr(args, "ashare", False):
        from ma_engine.adapters.ashare import AShareAdapter

        cache = getattr(args, "cache", None) or DEFAULT_CACHE
        return list(AShareAdapter(limit=getattr(args, "limit", None),
                                  cache_path=cache).companies())
    return list(DummyAdapter(n=args.n).companies())


def _print_ranking(companies: list[Company], top: int) -> None:
    reports = rank(companies)
    print(f"\nScreened {len(reports)} companies. "
          f"Top {top} by succession score:\n")
    print(f"{'#':>3}  {'score':>5}  {'company':<24} {'owner':<12} {'signal summary'}")
    print("-" * 110)
    for i, r in enumerate(reports[:top], 1):
        strongest = max(r.signals, key=lambda s: r.contributions.get(s.key, 0))
        owner = r.company.controller()
        print(f"{i:>3}  {r.total:>5.0f}  {r.company.name:<24} "
              f"{(owner.name if owner else ', '):<12} {strongest.reason}")
    print()
    best = reports[0]
    print("Strongest candidate in detail:\n")
    print(best.explain())
    print("\nBuyer shortlist:")
    for m in match_buyers(best.company)[:3]:
        print(f"  - {m.name} (fit {m.fit:.0%}): {m.rationale}")


def cmd_demo(args: argparse.Namespace) -> None:
    print("MA Engine, demo on synthetic data.")
    print("Every company and person below is fictional.")
    _print_ranking(_load(args), args.top)
    print("\nNext: `ma-engine dossier --name <company>` writes the full dossier.")


def cmd_score(args: argparse.Namespace) -> None:
    _print_ranking(_load(args), args.top)


def cmd_export(args: argparse.Namespace) -> None:
    from ma_engine import export

    reports = rank(_load(args))
    csv_path = export.write_csv(reports, args.csv_out)
    md_path = export.write_markdown(reports, args.md_out, top=args.top)
    print(f"\nWrote {len(reports)} scored companies to:")
    print(f"  {csv_path}")
    print(f"  {md_path}  (top {args.top})")
    print("\n" + export.summarise(reports))


def _labelled(args: argparse.Namespace):
    from ma_engine import tune as t

    pairs = t.match_labels(_load(args), t.read_labels(args.labels))
    if not pairs:
        print("No company in the data matched a row in the labels file. The "
              "`company` column must hold the company name or its source id.",
              file=sys.stderr)
        sys.exit(1)
    return t, pairs


def cmd_evaluate(args: argparse.Namespace) -> None:
    from ma_engine.scoring.engine import load_config

    t, pairs = _labelled(args)
    print(t.evaluate(pairs, load_config(args.config), k=args.k))


def cmd_tune(args: argparse.Namespace) -> None:
    from ma_engine.scoring.engine import load_config

    t, pairs = _labelled(args)
    base = load_config(args.config)
    print(f"Tuning on {len(pairs)} labelled companies, {args.trials} trials, "
          f"{args.folds}-fold cross-validation.")
    best, before, after = t.tune(pairs, base, trials=args.trials,
                                 folds=args.folds, k=args.k, seed=args.seed,
                                 log=print)
    print(f"\nHeld-out AUC: {before:.3f} before, {after:.3f} after tuning.")
    print("On the full labelled set with the tuned config:")
    print(t.evaluate(pairs, best, k=args.k))
    print(f"\nWrote {t.write_config(best, args.out)}")
    print(f"Use it with: MA_ENGINE_SCORING_CONFIG={args.out} ma-engine score ...")


def cmd_dossier(args: argparse.Namespace) -> None:
    companies = _load(args)
    hits = [c for c in companies if args.name in c.name]
    if not hits:
        print(f"No company matching '{args.name}' found.", file=sys.stderr)
        sys.exit(1)
    text = build_dossier(hits[0], use_llm=not args.no_llm)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Dossier written to {args.out}")
    else:
        print(text)


def main() -> None:
    parser = argparse.ArgumentParser(prog="ma-engine", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_demo = sub.add_parser("demo", help="run the pipeline on synthetic data")
    p_demo.add_argument("--n", type=int, default=200, help="synthetic companies to generate")
    p_demo.add_argument("--top", type=int, default=15)
    p_demo.set_defaults(func=cmd_demo)

    p_score = sub.add_parser("score", help="rank companies from a CSV or A-shares")
    p_score.add_argument("--csv", help="score companies from your own CSV")
    p_score.add_argument("--ashare", action="store_true",
                         help="score listed private companies from public "
                              "disclosures (free, no credentials)")
    p_score.add_argument("--limit", type=int,
                         help="only process the first N listed companies")
    p_score.add_argument("--cache", help="path to the A-share cache file")
    p_score.add_argument("--n", type=int, default=200)
    p_score.add_argument("--top", type=int, default=15)
    p_score.set_defaults(func=cmd_score)

    p_exp = sub.add_parser("export", help="write the scored table and summary")
    p_exp.add_argument("--ashare", action="store_true",
                       help="use listed-company data")
    p_exp.add_argument("--csv", help="score companies from your own CSV")
    p_exp.add_argument("--cache", help="path to the A-share cache file")
    p_exp.add_argument("--limit", type=int)
    p_exp.add_argument("--n", type=int, default=200)
    p_exp.add_argument("--top", type=int, default=50,
                       help="rows in the markdown watchlist")
    p_exp.add_argument("--csv-out", default="data/succession_watchlist.csv")
    p_exp.add_argument("--md-out", default="data/succession_watchlist.md")
    p_exp.set_defaults(func=cmd_export)

    def _data_args(p):
        p.add_argument("--labels", required=True,
                       help="CSV with columns company,sold (1 = changed hands)")
        p.add_argument("--csv", help="score companies from your own CSV")
        p.add_argument("--ashare", action="store_true", help="use listed-company data")
        p.add_argument("--cache", help="path to the A-share cache file")
        p.add_argument("--limit", type=int)
        p.add_argument("--n", type=int, default=200)
        p.add_argument("--config", help="scoring config to start from (default: bundled)")
        p.add_argument("--k", type=int, default=50, help="k for precision@k and lift@k")

    p_eval = sub.add_parser("evaluate", help="measure a config against known outcomes")
    _data_args(p_eval)
    p_eval.set_defaults(func=cmd_evaluate)

    p_tune = sub.add_parser("tune", help="fit weights and curves to known outcomes")
    _data_args(p_tune)
    p_tune.add_argument("--trials", type=int, default=100)
    p_tune.add_argument("--folds", type=int, default=5)
    p_tune.add_argument("--seed", type=int, default=0)
    p_tune.add_argument("--out", default="tuned_config.yaml")
    p_tune.set_defaults(func=cmd_tune)

    p_doss = sub.add_parser("dossier", help="full dossier for one company")
    p_doss.add_argument("--name", required=True, help="company name or part of it")
    p_doss.add_argument("--csv", help="optional CSV source; default is demo data")
    p_doss.add_argument("--ashare", action="store_true",
                        help="use listed-company data")
    p_doss.add_argument("--limit", type=int)
    p_doss.add_argument("--cache", help="path to the A-share cache file")
    p_doss.add_argument("--n", type=int, default=200)
    p_doss.add_argument("--no-llm", action="store_true",
                        help="skip the LLM even if a key is configured")
    p_doss.add_argument("--out", help="write to this file instead of stdout")
    p_doss.set_defaults(func=cmd_dossier)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
