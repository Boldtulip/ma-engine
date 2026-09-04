"""Smoke tests for the command line.

These exist because a syntax error in cli.py once passed the whole
suite: nothing else imports that module. Each command is run through
its own function with parsed arguments, on the bundled synthetic data.
"""

import csv
import sys

import pytest

from ma_engine import cli


def run(argv: list[str]) -> None:
    old = sys.argv
    sys.argv = ["ma-engine", *argv]
    try:
        cli.main()
    finally:
        sys.argv = old


def test_help_lists_every_command(capsys):
    with pytest.raises(SystemExit):
        run(["--help"])
    out = capsys.readouterr().out
    for cmd in ("demo", "score", "export", "evaluate", "tune", "dossier"):
        assert cmd in out


def test_demo_runs(capsys):
    run(["demo", "--n", "30", "--top", "3"])
    out = capsys.readouterr().out
    assert "Screened 30 companies" in out
    assert "fictional" in out


def test_dossier_runs_without_llm(capsys):
    run(["dossier", "--name", "有限公司", "--n", "30", "--no-llm"])
    assert "## Succession analysis" in capsys.readouterr().out


def test_export_writes_files(tmp_path, capsys):
    csv_out, md_out = tmp_path / "w.csv", tmp_path / "w.md"
    run(["export", "--n", "30", "--top", "5",
         "--csv-out", str(csv_out), "--md-out", str(md_out)])
    assert csv_out.exists() and md_out.exists()
    assert "Companies scored: 30" in capsys.readouterr().out


def test_evaluate_and_tune_run(tmp_path, capsys):
    pytest.importorskip("optuna")
    from ma_engine.adapters.dummy import DummyAdapter

    labels = tmp_path / "labels.csv"
    with open(labels, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["company", "sold"])
        for i, c in enumerate(DummyAdapter(n=60).companies()):
            w.writerow([c.name, i % 4 == 0])
    run(["evaluate", "--labels", str(labels), "--n", "60", "--k", "10"])
    assert "AUC" in capsys.readouterr().out

    out = tmp_path / "tuned.yaml"
    run(["tune", "--labels", str(labels), "--n", "60", "--k", "10",
         "--trials", "3", "--folds", "2", "--out", str(out)])
    assert out.exists()
    assert "after tuning" in capsys.readouterr().out
