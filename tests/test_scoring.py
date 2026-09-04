from ma_engine.adapters.base import Company, Person
from ma_engine.adapters.dummy import DummyAdapter
from ma_engine.matching.matcher import match_buyers
from ma_engine.scoring.engine import rank, score_company
from ma_engine.signals.age import age_floor, split_name


def old_founder_no_heir() -> Company:
    return Company(
        name="测试宏泰机械有限公司",
        industry="精密机械制造",
        region="浙江温州",
        founded_year=1993,
        legal_rep="王建国",
        legal_rep_since=1993,
        shareholders=[Person("王建国", "实际控制人", 100.0)],
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
        shareholders=[Person("李浩", "实际控制人", 60.0, age=45),
                      Person("李子轩", "股东", 40.0, age=24)],
        executives=[Person("李浩", "执行董事", age=45)],
        revenue_m=80.0,
        net_profit_m=6.0,
        source="test",
    )


def test_age_curve_peaks_in_the_sixties():
    """The decision window is the sixties, not extreme old age. An
    owner still in the chair at 82 has shown he will not sell."""
    from ma_engine.signals.age import _age_to_score

    assert _age_to_score(66) == 1.0
    assert _age_to_score(45) < _age_to_score(58) < _age_to_score(64)
    assert _age_to_score(82) < _age_to_score(66)
    assert _age_to_score(87) < _age_to_score(72)
    # but old age is never treated as no signal at all
    assert _age_to_score(85) > _age_to_score(50)


def test_split_name():
    assert split_name("王建国") == ("王", "建国")
    assert split_name("欧阳修文") == ("欧阳", "修文")


def test_age_floor_from_tenure():
    """A long tenure puts a floor under the owner's age: they were old
    enough to run a company when they started."""
    company = old_founder_no_heir()          # in the role since 1993
    floor, since = age_floor(company, 30, year=2026)
    assert since == 1993
    assert floor == 30 + (2026 - 1993)

    # No start date and no founding year means no bound is offered.
    bare = Company(name="x", legal_rep="王建国")
    assert age_floor(bare, 30, year=2026) == (None, None)


def test_age_signal_says_it_is_a_bound_not_a_measurement():
    report = score_company(old_founder_no_heir())
    age = next(s for s in report.signals if s.key == "founder_age")
    assert "at least about" in age.reason
    assert age.confidence < 0.95        # below a disclosed age


def test_disclosed_age_beats_a_bound_on_confidence():
    disclosed = Company(
        name="y", legal_rep="王建国", legal_rep_since=2020,
        shareholders=[Person("王建国", "实际控制人", 100.0, age=66)])
    report = score_company(disclosed)
    age = next(s for s in report.signals if s.key == "founder_age")
    assert "66 years old (disclosed)" in age.reason
    assert age.confidence == 0.95


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
