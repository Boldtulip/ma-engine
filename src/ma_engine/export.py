"""Export scored companies as a table, and summarise the population.

The summary is the headline: how many companies are owner-controlled,
how many of those owners are past the age where succession becomes a
live question, and how many have no visible successor.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ma_engine.scoring.engine import ScoreReport

COLUMNS = [
    "rank", "score", "company", "industry", "region", "owner", "owner_age",
    "age_source", "owner_since", "revenue_m", "net_profit_m", "pledge_ratio",
    "heir_visible", "top_reason", "source",
]


def _row(rank: int, report: ScoreReport) -> dict:
    c = report.company
    owner = c.controller()
    signals = {s.key: s for s in report.signals}
    age_signal = signals.get("founder_age")
    disclosed = bool(age_signal and "disclosed" in age_signal.reason)
    heir = signals.get("heir_absence")
    strongest = max(report.signals, key=lambda s: report.contributions.get(s.key, 0))

    age = owner.age if owner else None
    if age is None and age_signal:
        # Pull the bound out of the reason rather than recomputing it.
        import re

        m = re.search(r"at least about (\d+)", age_signal.reason)
        age = int(m.group(1)) if m else None

    return {
        "rank": rank,
        "score": f"{report.total:.0f}",
        "company": c.name,
        "industry": c.industry,
        "region": c.region,
        "owner": owner.name if owner else "",
        "owner_age": age if age is not None else "",
        "age_source": "disclosed" if disclosed else ("tenure_floor" if age else "unknown"),
        "owner_since": c.legal_rep_since or "",
        "revenue_m": f"{c.revenue_m:.1f}" if c.revenue_m else "",
        "net_profit_m": f"{c.net_profit_m:.1f}" if c.net_profit_m else "",
        "pledge_ratio": f"{c.pledge_ratio:.3f}" if c.pledge_ratio else "",
        "heir_visible": "no" if (heir and heir.score >= 0.5) else "yes/unclear",
        "top_reason": strongest.reason,
        "source": c.source,
    }


def write_csv(reports: list[ScoreReport], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for i, report in enumerate(reports, 1):
            writer.writerow(_row(i, report))
    return path


def _heading(reports: list[ScoreReport]) -> tuple[str, str]:
    """Title and note, honest about where the data came from."""
    source = reports[0].company.source if reports else ""
    if source.startswith("ashare"):
        return (
            "Succession watchlist, listed private companies in China",
            "Scored from companies' own public disclosures. Ages marked as "
            "disclosed come from those filings; any others are estimates and "
            "are labelled. A high score means a professional should look here "
            "first. It is not a claim that anyone intends to sell.",
        )
    if source.startswith("dummy"):
        return (
            "Succession watchlist, demonstration data",
            "Every company and person below is fictional, generated to "
            "demonstrate the scoring, and any resemblance to a real one is "
            "coincidence. Ages shown are lower bounds derived from how long "
            "the owner has held the company.",
        )
    return (
        "Succession watchlist",
        "Scored from the supplied data. An age is either disclosed in the "
        "records or a lower bound derived from how long the owner has held "
        "the company, and the two are marked differently.",
    )


def write_markdown(reports: list[ScoreReport], path: str | Path,
                   top: int = 50) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    title, note = _heading(reports)
    lines = [
        f"# {title}",
        "",
        note,
        "",
        "| # | Score | Company | Owner | Age | Industry | Why |",
        "|---:|---:|---|---|---:|---|---|",
    ]
    for i, report in enumerate(reports[:top], 1):
        r = _row(i, report)
        age = f"{r['owner_age']}" if r["owner_age"] != "" else "-"
        if r["age_source"] == "tenure_floor" and age != "-":
            age += "*"
        lines.append(
            f"| {i} | {r['score']} | {r['company']} | {r['owner']} | {age} | "
            f"{r['industry']} | {r['top_reason']} |")
    lines += ["", "\\* a lower bound from the owner's tenure, not a disclosed "
              "age.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def summarise(reports: list[ScoreReport]) -> str:
    """The headline numbers for this population."""
    total = len(reports)
    ages: list[int] = []
    disclosed = 0
    no_heir = 0
    for report in reports:
        signals = {s.key: s for s in report.signals}
        owner = report.company.controller()
        if owner and owner.age:
            ages.append(owner.age)
            disclosed += 1
        heir = signals.get("heir_absence")
        if heir and heir.score >= 0.5:
            no_heir += 1

    over_60 = sum(1 for a in ages if a >= 60)
    over_70 = sum(1 for a in ages if a >= 70)
    lines = [
        f"Companies scored: {total}",
        f"Owners with a disclosed age: {disclosed}",
    ]
    if ages:
        lines += [
            f"  aged 60 or over: {over_60} ({over_60 / len(ages):.0%} of those)",
            f"  aged 70 or over: {over_70} ({over_70 / len(ages):.0%} of those)",
            f"  median owner age: {sorted(ages)[len(ages) // 2]}",
        ]
    lines.append(
        f"No successor visible in the records: {no_heir} "
        f"({no_heir / total:.0%})" if total else "")
    return "\n".join(line for line in lines if line)
