"""Buyer matching.

The point of a shortlist is to rank. A buyer type whose score is the
same for every company adds nothing to a ranking, however well its
rationale reads, so the first test here guards against that.
"""

import pytest

from ma_engine.adapters.base import Company, Person
from ma_engine.adapters.dummy import DummyAdapter
from ma_engine.matching.matcher import load_knowledge, match_buyers


def company(**kw) -> Company:
    base = dict(
        name="示例测试有限公司", industry="五金工具", region="浙江温州",
        founded_year=1995, legal_rep="王建国", legal_rep_since=1995,
        shareholders=[Person("王建国", "实际控制人", 100.0)],
        executives=[Person("王建国", "执行董事")],
        revenue_m=80.0, net_profit_m=6.0, source="test",
    )
    base.update(kw)
    return Company(**base)


def test_every_buyer_type_discriminates():
    """No buyer type may return the same score for every company."""
    scores: dict[str, set] = {}
    for c in DummyAdapter(n=150).companies():
        for m in match_buyers(c):
            scores.setdefault(m.key, set()).add(m.fit)
    constant = [k for k, v in scores.items() if len(v) < 2]
    assert not constant, f"these buyer types score every company alike: {constant}"


def test_all_knowledge_buyers_are_matched():
    keys = {b["key"] for b in load_knowledge()["buyers_china"]["buyers"]}
    assert {m.key for m in match_buyers(company())} == keys


def test_scores_stay_in_range_and_sort():
    matches = match_buyers(company())
    assert all(0.0 <= m.fit <= 1.0 for m in matches)
    assert [m.fit for m in matches] == sorted((m.fit for m in matches), reverse=True)


def test_trade_buyer_prefers_a_fragmented_trade():
    hardware = _trade(company(industry="五金工具"))
    software = _trade(company(industry="计算机软件"))
    assert hardware.fit > software.fit
    assert "fragmented" in hardware.rationale


def test_trade_buyer_prefers_a_company_a_peer_can_afford():
    small = _trade(company(revenue_m=80.0))
    large = _trade(company(revenue_m=900.0))
    assert small.fit > large.fit
    assert "from its own cash" in small.rationale
    assert "beyond what most peers fund" in large.rationale


@pytest.mark.parametrize("kw, phrase", [
    ({"pledge_ratio": 0.8}, "pledged stake has to be cleared"),
    ({"litigation_count": 7}, "travels fast inside a cluster"),
])
def test_trade_buyer_marks_what_would_put_a_peer_off(kw, phrase):
    clean = _trade(company())
    troubled = _trade(company(**kw))
    assert troubled.fit < clean.fit
    assert phrase in troubled.rationale


def _trade(c: Company):
    return next(m for m in match_buyers(c) if m.key == "trade_buyer")
