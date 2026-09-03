"""Buyer matching.

Reads the knowledge base and ranks buyer categories for one target
company, each with a written rationale. This is the automated
version of a banker's buyer-list memo. The rules here are deliberately simple and
inspectable; the knowledge files carry the substance.

If an Anthropic API key is available, the LLM writes a fuller
rationale on top of the rule-based ranking. Without a key, the
rule-based output stands on its own.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from ma_engine.adapters.base import Company


def _default_knowledge_dir() -> Path:
    """Find the knowledge base.

    Order: an explicit MA_ENGINE_KNOWLEDGE_DIR, then a `knowledge` folder
    beside the installed package, then the repository layout. The
    environment variable is the supported way to point the engine at
    your own private knowledge base instead of the bundled one.
    """
    env = os.environ.get("MA_ENGINE_KNOWLEDGE_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / "knowledge",   # installed alongside the package
        here.parents[3] / "knowledge",   # repository checkout
        Path.cwd() / "knowledge",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[1]


KNOWLEDGE_DIR = _default_knowledge_dir()


@dataclass
class BuyerMatch:
    key: str
    name: str
    fit: float          # 0-1
    rationale: str


@lru_cache(maxsize=8)
def _load_dir(knowledge_dir: str) -> dict:
    path = Path(knowledge_dir)
    if not path.is_dir():
        raise FileNotFoundError(
            f"No knowledge base at {path}. Install the project from its "
            f"repository (pip install -e .), or set MA_ENGINE_KNOWLEDGE_DIR to "
            f"your own knowledge folder."
        )
    out = {}
    for f in sorted(path.glob("*.yaml")):
        with open(f, encoding="utf-8") as fh:
            out[f.stem] = yaml.safe_load(fh)
    return out


def load_knowledge(knowledge_dir: Path | str = KNOWLEDGE_DIR) -> dict:
    """Read every YAML file in the knowledge base. Cached, because the
    dossier and matcher both read it for every company."""
    return _load_dir(str(knowledge_dir))


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
            # Control-oriented PE in China writes cheques of roughly
            # 450M to 1.6bn. Below that the structure does not pay for
            # itself, whatever the fit looks like on paper.
            if revenue >= 300 and profit > 20:
                fit += 0.25
                reasons.append("large enough for a control fund to justify the "
                               "structure, and sized for a later sale to a listed buyer")
            else:
                fit -= 0.35
                reasons.append("below the size where China's control funds actually "
                               "buy; their deals cluster far above this")
            if company.pledge_ratio > 0.5:
                fit -= 0.2
                reasons.append("a heavily pledged stake complicates a control purchase")

        elif b["key"] == "state_platform":
            asset_heavy = any(w in company.industry
                              for w in ("制造", "零部件", "机械", "建材", "化工",
                                        "五金", "纺织", "食品", "包装"))
            if asset_heavy:
                fit += 0.25
                reasons.append("manufacturing with local employment and hard assets "
                               "is what state platforms exist to keep")
            else:
                fit -= 0.15
                reasons.append("asset-light value prices poorly against a formal "
                               "appraisal")
            reasons.append("expect the filed appraisal to cap the price and the "
                           "approval chain to take four to nine months")

        elif b["key"] == "search_fund":
            if 30 <= revenue <= 200:
                fit += 0.3
                reasons.append(f"revenue of {revenue:.0f}M CNY sits in the stated "
                               f"search-fund range")
            else:
                fit -= 0.25
                reasons.append("outside the size range a search fund can buy and run")
            # Fit is not liquidity: no mainland search fund has closed
            # a deal. Say so every time rather than flattering the rank.
            reasons.append("but no search fund has completed a mainland acquisition "
                           "to date, so treat this as fit, not as available money")

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
            if revenue < 800:
                reasons.append("China revenue below 800M means no merger filing is "
                               "triggered, and manufacturing carries no negative-list bar")

        matches.append(BuyerMatch(
            key=b["key"],
            name=f'{b["name_cn"]} ({b["name_en"]})',
            fit=round(max(0.0, min(1.0, fit)), 2),
            rationale="; ".join(reasons) if reasons else b["motive"].strip(),
        ))

    return sorted(matches, key=lambda m: -m.fit)
