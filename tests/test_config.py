"""The scoring config decides which signals run and with what
parameters. These tests cover the promise the README makes: the
bundled rules are an example, and you can change them, drop them, or
add your own without touching the engine."""

from pathlib import Path

import pytest

from ma_engine.adapters.base import Company, Person
from ma_engine.scoring.engine import DEFAULT_CONFIG, load_config, score_company
from ma_engine.signals import REGISTRY, compute

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = ROOT / "examples" / "scoring_config.yaml"


def company() -> Company:
    return Company(
        name="测试宏泰机械有限公司",
        founded_year=1995,
        legal_rep="王建国",
        legal_rep_since=1995,
        shareholders=[Person("王建国", "实际控制人", 100.0, age=66)],
        executives=[Person("王建国", "董事长", age=66)],
        pledge_ratio=0.5,
        source="test",
    )


def test_bundled_config_runs_the_four_example_signals():
    report = score_company(company(), load_config(DEFAULT_CONFIG))
    assert {s.key for s in report.signals} == {
        "founder_age", "owner_tenure", "heir_absence", "sell_pressure"}


def test_parameters_come_from_the_config():
    base = load_config(DEFAULT_CONFIG)
    flat = {"signals": {"founder_age": {"weight": 1.0,
                                        "curve": [[0, 0.5], [100, 0.5]]}}}
    assert score_company(company(), base).contributions["founder_age"] != \
        score_company(company(), flat).contributions["founder_age"]
    assert score_company(company(), flat).signals[0].score == 0.5


def test_dropping_a_signal_removes_it():
    only_age = {"signals": {"founder_age": {"weight": 1.0}}}
    report = score_company(company(), only_age)
    assert [s.key for s in report.signals] == ["founder_age"]
    assert report.total == pytest.approx(
        100 * report.signals[0].score * report.signals[0].confidence, abs=0.1)


def test_example_plugin_adds_a_custom_signal():
    cfg = load_config(EXAMPLE_CONFIG)
    report = score_company(company(), cfg)
    keys = {s.key for s in report.signals}
    assert "concentrated_ownership" in keys
    assert "owner_tenure" not in keys          # dropped by that config
    custom = next(s for s in report.signals if s.key == "concentrated_ownership")
    assert custom.score == 1.0                 # 100% owner
    assert "王建国 holds 100%" in custom.reason


def test_unknown_signal_name_is_a_clear_error():
    with pytest.raises(KeyError, match="no signal with that name is registered"):
        compute(company(), {"signals": {"does_not_exist": {"weight": 1}}})


def test_registry_holds_the_builtins_after_a_run():
    score_company(company())
    assert {"founder_age", "owner_tenure", "heir_absence", "sell_pressure"} <= set(REGISTRY)
