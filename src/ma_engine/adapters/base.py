"""Core data model and the adapter interface.

Every data source (dummy data, CSV, A-share disclosures, commercial APIs)
is an adapter that returns the same `Company` objects. The rest of the
engine never knows where the data came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass
class Person:
    """A shareholder or executive. Age is optional because Chinese
    registries do not publish it for private companies; when it is
    missing, the engine estimates it from the given name (see
    signals/age.py)."""

    name: str
    role: str = ""                # e.g. "股东", "董事长", "监事"
    ownership_pct: float = 0.0    # 0-100, for shareholders
    age: Optional[int] = None     # exact age when disclosed (listed companies)
    is_company: bool = False      # corporate shareholder, not a person


@dataclass
class Company:
    name: str
    industry: str = ""
    region: str = ""              # province or city
    founded_year: Optional[int] = None
    legal_rep: str = ""           # 法定代表人 / chairman
    legal_rep_since: Optional[int] = None  # year the current legal rep took the role
    shareholders: list[Person] = field(default_factory=list)
    executives: list[Person] = field(default_factory=list)
    revenue_m: Optional[float] = None      # annual revenue, million CNY
    net_profit_m: Optional[float] = None   # net profit, million CNY
    pledge_ratio: float = 0.0     # share of controller's equity pledged, 0-1
    litigation_count: int = 0     # published cases naming the company
    is_private: bool = True       # 民营企业 (not state-owned)
    source: str = ""              # which adapter produced this record

    def controller(self) -> Optional[Person]:
        """The person the succession analysis is about.

        Where the records name an actual controller (实际控制人), that
        person wins outright — a large institutional shareholder is not
        the owner in the sense that matters here. Otherwise fall back
        to the largest individual shareholder, then the legal
        representative.
        """
        named = [s for s in self.shareholders
                 if not s.is_company and "实际控制人" in s.role]
        if named:
            return max(named, key=lambda p: p.ownership_pct)
        people = [s for s in self.shareholders if not s.is_company]
        if people:
            return max(people, key=lambda p: p.ownership_pct)
        if self.legal_rep:
            return Person(name=self.legal_rep, role="法定代表人")
        return None


class Adapter:
    """Interface every data source implements."""

    name = "base"

    def companies(self) -> Iterable[Company]:
        raise NotImplementedError
