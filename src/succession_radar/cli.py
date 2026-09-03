"""Command line interface.

Three commands:
  radar demo                 run the whole pipeline on bundled synthetic data
  radar score --csv FILE     rank companies from your own CSV
  radar dossier --name NAME  full dossier for one company (demo or CSV data)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from succession_radar.adapters.base import Company
from succession_radar.adapters.csv_adapter import CsvAdapter
from succession_radar.adapters.dummy import DummyAdapter
from succession_radar.agent.dossier import build_dossier
from succession_radar.matching.matcher import match_buyers
from succession_radar.scoring.engine import rank


def _load(args: argparse.Namespace) -> list[Company]:
    if getattr(args, "csv", None):
        return list(CsvAdapter(args.csv).companies())
    return list(DummyAdapter(n=args.n).companies())


def _print_ranking(companies: list[Company], top: int) -> None:
    reports = rank(companies)
    print(f"\nScreened {len(reports)} companies. "
          f"Top {top} by succession score:\n")
    print(f"{'#':>3}  {'score':>5}  {'company':<28} {'owner':<10} {'signal summary'}")
    print("-" * 100)
    for i, r in enumerate(reports[:top], 1):
        strongest = max(r.signals, key=lambda s: r.contributions.get(s.key, 0))
        print(f"{i:>3}  {r.total:>5.0f}  {r.company.name:<28} "
              f"{r.company.legal_rep:<10} {strongest.reason}")
    print()
    best = reports[0]
    print("Strongest candidate in detail:\n")
    print(best.explain())
    print("\nBuyer shortlist:")
    for m in match_buyers(best.company)[:3]:
        print(f"  - {m.name} (fit {m.fit:.0%}): {m.rationale}")


def cmd_demo(args: argparse.Namespace) -> None:
    print("Succession Radar — demo on synthetic data.")
    print("Every company and person below is fictional.")
    _print_ranking(_load(args), args.top)
    print("\nNext: `radar dossier --name <company>` writes the full dossier.")


def cmd_score(args: argparse.Namespace) -> None:
    _print_ranking(_load(args), args.top)


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
    parser = argparse.ArgumentParser(prog="radar", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_demo = sub.add_parser("demo", help="run the pipeline on synthetic data")
    p_demo.add_argument("--n", type=int, default=200, help="synthetic companies to generate")
    p_demo.add_argument("--top", type=int, default=15)
    p_demo.set_defaults(func=cmd_demo)

    p_score = sub.add_parser("score", help="rank companies from a CSV")
    p_score.add_argument("--csv", required=True)
    p_score.add_argument("--n", type=int, default=200)
    p_score.add_argument("--top", type=int, default=15)
    p_score.set_defaults(func=cmd_score)

    p_doss = sub.add_parser("dossier", help="full dossier for one company")
    p_doss.add_argument("--name", required=True, help="company name or part of it")
    p_doss.add_argument("--csv", help="optional CSV source; default is demo data")
    p_doss.add_argument("--n", type=int, default=200)
    p_doss.add_argument("--no-llm", action="store_true",
                        help="skip the LLM even if a key is configured")
    p_doss.add_argument("--out", help="write to this file instead of stdout")
    p_doss.set_defaults(func=cmd_dossier)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
