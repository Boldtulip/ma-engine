"""Dossier tests.

The LLM path cannot be exercised for real in CI, so it is tested with
a stub. What matters most is the failure behaviour: no missing key,
network error, or refusal may ever stop the tool from producing a
dossier.
"""

import sys
import types

import pytest

from ma_engine.adapters.base import Company, Person
from ma_engine.agent import dossier as mod


def sample_company() -> Company:
    return Company(
        name="测试宏泰机械有限公司",
        industry="精密机械制造",
        region="浙江温州",
        founded_year=1995,
        legal_rep="王建国",
        legal_rep_since=1995,
        shareholders=[Person("王建国", "实际控制人", 100.0, age=66)],
        executives=[Person("王建国", "董事长", age=66)],
        revenue_m=120.0,
        net_profit_m=10.0,
        source="test",
    )


def test_template_dossier_has_the_expected_sections():
    text = mod.build_dossier(sample_company(), use_llm=False)
    for heading in ("## Succession analysis", "## Buyer shortlist",
                    "## What the seller should know", "## Open questions"):
        assert heading in text
    assert "王建国" in text
    # The disclaimer must survive any refactor.
    assert "not statements of fact" in text


def _install_fake_anthropic(monkeypatch, behaviour):
    """Put a stub `anthropic` module in place of the real one."""
    fake = types.ModuleType("anthropic")

    class FakeMessages:
        def create(self, **kwargs):
            return behaviour(kwargs)

    class FakeClient:
        def __init__(self, *a, **kw):
            self.messages = FakeMessages()

    fake.Anthropic = FakeClient
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return fake


def test_llm_path_returns_model_text(monkeypatch):
    captured = {}

    def behaviour(kwargs):
        captured.update(kwargs)
        block = types.SimpleNamespace(type="text", text="# Model written dossier")
        return types.SimpleNamespace(stop_reason="end_turn", content=[block])

    _install_fake_anthropic(monkeypatch, behaviour)
    text = mod.build_dossier(sample_company(), use_llm=True)
    assert text == "# Model written dossier"
    # The knowledge base must actually be injected, not just referenced.
    system_text = captured["system"][0]["text"]
    assert "buyers_china" in system_text or "地方国资平台" in system_text


def test_missing_credentials_fall_back_to_template(monkeypatch, capsys):
    """Constructing the client raises when no key is configured, and
    that exception is not an APIError. It must not escape."""

    fake = types.ModuleType("anthropic")

    class Boom:
        def __init__(self, *a, **kw):
            raise RuntimeError("The api_key client option must be set")

    fake.Anthropic = Boom
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    text = mod.build_dossier(sample_company(), use_llm=True)
    assert "## Succession analysis" in text          # template, not a crash
    assert "could not reach the model" in capsys.readouterr().out


def test_refusal_falls_back_to_template(monkeypatch):
    def behaviour(kwargs):
        return types.SimpleNamespace(stop_reason="refusal", content=[])

    _install_fake_anthropic(monkeypatch, behaviour)
    text = mod.build_dossier(sample_company(), use_llm=True)
    assert "## Succession analysis" in text


def test_empty_model_response_falls_back(monkeypatch):
    def behaviour(kwargs):
        return types.SimpleNamespace(stop_reason="end_turn", content=[])

    _install_fake_anthropic(monkeypatch, behaviour)
    assert "## Succession analysis" in mod.build_dossier(sample_company(),
                                                         use_llm=True)


@pytest.mark.parametrize("exc", [RuntimeError("network down"),
                                 TimeoutError("timed out")])
def test_any_error_falls_back(monkeypatch, exc):
    def behaviour(kwargs):
        raise exc

    _install_fake_anthropic(monkeypatch, behaviour)
    assert "## Succession analysis" in mod.build_dossier(sample_company(),
                                                         use_llm=True)
