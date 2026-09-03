"""Buyer matching.

Reads the knowledge base and ranks buyer categories for one target
company, each with a written rationale — the automated version of a
banker's buyer-list memo. The rules here are deliberately simple and
inspectable; the knowledge files carry the substance.

If an Anthropic API key is available, the LLM writes a fuller
rationale on top of the rule-based ranking. Without a key, the
rule-based output stands on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from succession_radar.adapters.base import Company

KNOWLEDGE_DIR = Path(__file__).parents[3] / "knowledge"


@dataclass
class BuyerMatch:
    key: str
    name: str
    fit: float          # 0-1
    rationale: str


def load_knowledge(knowledge_dir: Path | str = KNOWLEDGE_DIR) -> dict:
    out = {}
    for f in Path(knowledge_dir).glob("*.yaml"):
        with open(f, encoding="utf-8") as fh:
            out[f.stem] = yaml.safe_load(fh)
    return out


def match_buyers(company: Company, knowledge: dict | None = None) -> list[BuyerMatch]:
    knowledge = knowledge or load_knowledge()
    buyers = knowledge.get("buyers_china", {}).get("buyers", [])

    profit = company.net_profit_m or 0.0
    revenue = company.revenue_m or 0.0
    matches: list[BuyerMatch] = []

    for b in buyers:
        fit = 0.5
        reasons: list[str] = []

        if b["key"] == "listed_company":
            if profit >= 20:
                fit += 0.35
                reasons.append(
                    f"net profit of {profit:.0f}M CNY is large enough to matter "
                    f"to a listed acquirer's earnings")
            else:
                fit -= 0.3
                reasons.append("profit is below the size a listed company typically wants")
            if company.litigation_count > 3:
                fit -= 0.2
                reasons.append("litigation record would worry listed-company diligence")

        elif b["key"] == "industrial_fund":
            if profit > 5 and revenue > 50:
                fit += 0.25
                reasons.append("stable size and profit fit the hold-improve-exit model")
            if company.pledge_ratio > 0.5:
                fit -= 0.2
                reasons.append("a heavily pledged stake complicates a control purchase")

        elif b["key"] == "state_platform":
            if "制造" in company.industry or "零部件" in company.industry:
                fit += 0.25
                reasons.append("manufacturing with local employment is what "
                               "state platforms exist to keep")
            reasons.append("price will follow a formal appraisal; certainty is high, "
                           "premium is not")

        elif b["key"] == "search_fund":
            if 30 <= revenue <= 200:
                fit += 0.3
                reasons.append(f"revenue of {revenue:.0f}M CNY sits in the classic "
                               f"search-fund range")
            else:
                fit -= 0.25
                reasons.append("outside the size range a search fund can buy and run")

        elif b["key"] == "trade_buyer":
            fit += 0.2
            reasons.append("peers in the same industry cluster already trust the "
                           "company; this is where most SME deals actually close")

        elif b["key"] == "foreign_strategic":
            if profit > 10:
                fit += 0.1
                reasons.append("profitable niche could interest a foreign strategic")
            else:
                fit -= 0.2
                reasons.append("too small for a typical cross-border process")

        matches.append(BuyerMatch(
            key=b["key"],
            name=f'{b["name_cn"]} ({b["name_en"]})',
            fit=round(max(0.0, min(1.0, fit)), 2),
            rationale="; ".join(reasons) if reasons else b["motive"].strip(),
        ))

    return sorted(matches, key=lambda m: -m.fit)
