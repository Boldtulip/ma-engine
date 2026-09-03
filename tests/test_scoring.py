from succession_radar.adapters.base import Company, Person
from succession_radar.adapters.dummy import DummyAdapter
from succession_radar.matching.matcher import match_buyers
from succession_radar.scoring.engine import rank, score_company
from succession_radar.signals.age import estimate_age, split_name


def old_founder_no_heir() -> Company:
    return Company(
        name="测试宏泰机械有限公司",
        industry="精密机械制造",
        region="浙江温州",
        founded_year=1993,
        legal_rep="王建国",
        legal_rep_since=1993,
        shareholders=[Person("王建国", "股东", 100.0)],
        executives=[Person("王建国", "执行董事")],
        revenue_m=120.0,
        net_profit_m=10.0,
        source="test",
    )


def young_founder_with_heir() -> Company:
    return Company(
        name="测试新宇电子有限公司",
        industry="电子元器件",
        region="广东东莞",
        founded_year=2015,
        legal_rep="李浩",
        legal_rep_since=2015,
        shareholders=[Person("李浩", "股东", 60.0), Person("李子轩", "股东", 40.0)],
        executives=[Person("李浩", "执行董事")],
        revenue_m=80.0,
        net_profit_m=6.0,
        source="test",
    )


def test_split_name():
    assert split_name("王建国") == ("王", "建国")
    assert split_name("欧阳修文") == ("欧阳", "修文")


def test_name_cohort_age():
    age, conf, _ = estimate_age("王建国", year=2026)
    assert age is not None and age > 65
    assert conf > 0


def test_old_founder_scores_higher():
    old = score_company(old_founder_no_heir())
    young = score_company(young_founder_with_heir())
    assert old.total > young.total
    assert 0 <= young.total <= 100


def test_explain_contains_reasons():
    text = score_company(old_founder_no_heir()).explain()
    assert "王建国" in text
    assert "/100" in text


def test_rank_and_match_on_dummy_data():
    companies = list(DummyAdapter(n=50).companies())
    reports = rank(companies)
    assert len(reports) == 50
    assert reports[0].total >= reports[-1].total
    matches = match_buyers(reports[0].company)
    assert matches and all(0 <= m.fit <= 1 for m in matches)
