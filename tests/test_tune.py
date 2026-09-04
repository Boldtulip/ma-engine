"""Evaluation and tuning.

Labels are synthetic here: a hidden rule decides which fictional
companies "sold", with noise, so the tests can check that the metrics
behave and that tuning against held-out folds does not make the
config worse. No real outcome data exists in this repository.
"""

import random

import pytest

from ma_engine import tune as t
from ma_engine.adapters.dummy import DummyAdapter
from ma_engine.scoring.engine import DEFAULT_CONFIG, load_config
from ma_engine.signals.age import age_floor


def labelled_companies(n: int = 300, seed: int = 1):
    """Sold if the owner's age floor is 60-80 and no same-surname
    younger person is on record, flipped 15% of the time."""
    rng = random.Random(seed)
    pairs = []
    for c in DummyAdapter(n=n, seed=seed).companies():
        owner = c.controller()
        age = age_floor(c, 30)[0] if owner else None
        heir = any(p.name != owner.name and p.name[0] == owner.name[0]
                   for p in c.shareholders + c.executives) if owner else False
        sold = 1 if (age and 60 <= age <= 80 and not heir) else 0
        if rng.random() < 0.15:
            sold = 1 - sold
        pairs.append((c, sold))
    return pairs


def test_auc_extremes():
    assert t.auc([0.9, 0.8, 0.1, 0.2], [1, 1, 0, 0]) == 1.0
    assert t.auc([0.1, 0.2, 0.9, 0.8], [1, 1, 0, 0]) == 0.0
    assert t.auc([0.5, 0.5, 0.5, 0.5], [1, 1, 0, 0]) == 0.5


def test_precision_and_lift():
    scores = [10, 9, 8, 7, 1, 1, 1, 1]
    labels = [1, 1, 0, 0, 0, 0, 0, 0]
    assert t.precision_at_k(scores, labels, 2) == 1.0
    assert t.lift_at_k(scores, labels, 2) == pytest.approx(1.0 / 0.25)


def test_read_and_match_labels(tmp_path):
    path = tmp_path / "labels.csv"
    path.write_text("company,sold\ndummy,1\n江苏利昌包装有限公司,0\n", encoding="utf-8")
    labels = t.read_labels(path)
    companies = list(DummyAdapter(n=50).companies())
    pairs = t.match_labels(companies, labels)
    assert pairs  # every dummy company has source "dummy", so all match on source
    assert all(y == 1 for _, y in pairs)


def test_read_labels_needs_the_two_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("name,outcome\nx,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="company"):
        t.read_labels(path)


def test_bundled_config_beats_chance_on_the_hidden_rule():
    ev = t.evaluate(labelled_companies(), load_config(DEFAULT_CONFIG), k=30)
    assert ev.n == 300 and ev.positives > 5
    assert ev.auc > 0.6
    assert ev.lift_at_k > 1.0


def test_suggest_config_keeps_shape_and_bounds():
    optuna = pytest.importorskip("optuna")
    base = load_config(DEFAULT_CONFIG)
    trial = optuna.trial.FixedTrial({})
    # FixedTrial needs every parameter; drive one real sampler trial instead.
    study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=0))
    cfg = t.suggest_config(study.ask(), base)
    assert set(cfg["signals"]) == set(base["signals"])
    curve = cfg["signals"]["founder_age"]["curve"]
    assert [x for x, _ in curve] == [x for x, _ in base["signals"]["founder_age"]["curve"]]
    assert all(0.0 <= y <= 1.0 for _, y in curve)
    assert 0.0 <= cfg["signals"]["sell_pressure"]["weight"] <= 1.0


def test_tuning_does_not_make_it_worse():
    pytest.importorskip("optuna")
    pairs = labelled_companies()
    best, before, after = t.tune(pairs, load_config(DEFAULT_CONFIG),
                                 trials=25, folds=3, seed=0)
    assert after >= before - 0.02
    assert set(best["signals"]) == {"founder_age", "owner_tenure",
                                    "heir_absence", "sell_pressure"}


def test_tune_refuses_tiny_label_sets():
    pytest.importorskip("optuna")
    with pytest.raises(ValueError):
        t.tune(labelled_companies(n=10), load_config(DEFAULT_CONFIG), trials=1)


def test_write_config_roundtrip(tmp_path):
    import yaml

    cfg = load_config(DEFAULT_CONFIG)
    out = t.write_config(cfg, tmp_path / "tuned.yaml")
    assert yaml.safe_load(out.read_text(encoding="utf-8"))["signals"].keys() == cfg["signals"].keys()
