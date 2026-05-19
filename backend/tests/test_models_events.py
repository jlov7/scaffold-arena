from __future__ import annotations

import pytest

from config.models import all_models_meta, cost_usd, get_model
from core import events
from core.provider import GeminiProvider, OpenAIProvider, OpenRouterProvider, get_provider
from config.settings import settings


def test_get_model_and_cost_usd() -> None:
    model = get_model("claude-sonnet-4-6")
    assert model.label == "Claude Sonnet 4.6"

    cost = cost_usd(1_000_000, 1_000_000, "claude-sonnet-4-6")
    assert cost == pytest.approx(18.0)


def test_get_model_unknown_raises() -> None:
    with pytest.raises(ValueError):
        get_model("missing")


def test_all_models_meta_contains_price_keys() -> None:
    models = all_models_meta()
    assert len(models) >= 2
    for entry in models:
        assert "id" in entry
        assert "provider" in entry
        assert "input_usd_per_mtok" in entry
        assert "output_usd_per_mtok" in entry


def test_get_provider_uses_model_registry() -> None:
    provider = get_provider("claude-sonnet-4-6", api_key_override="test-anthropic-key")
    assert provider.__class__.__name__ == "AnthropicProvider"


def test_get_provider_openai_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-openai-key")
    provider = get_provider("gpt-4.1-mini")
    assert provider.__class__.__name__ == "OpenAIProvider"


def test_get_provider_gemini_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")
    provider = get_provider("gemini-2.5-flash")
    assert provider.__class__.__name__ == "GeminiProvider"


def test_get_provider_openrouter_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", "test-openrouter-key")
    provider = get_provider("openrouter/openai/gpt-4.1-mini")
    assert provider.__class__.__name__ == "OpenRouterProvider"
    assert provider._resolve_model_id("openrouter/openai/gpt-4.1-mini") == "openai/gpt-4.1-mini"  # type: ignore[attr-defined]


def test_openai_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(RuntimeError):
        OpenAIProvider()


def test_gemini_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gemini_api_key", "")
    with pytest.raises(RuntimeError):
        GeminiProvider()


def test_openrouter_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    with pytest.raises(RuntimeError):
        OpenRouterProvider()


def test_sse_event_formatting_and_event_payloads() -> None:
    payload = events.run_started("run1", "extraction", ["bare"])
    frame = events.sse_event("run_started", payload, 7)
    assert frame.startswith("id: 7")
    assert "event: run_started" in frame
    assert '"run_id":"run1"' in frame
    assert "ts_ms" in payload


def test_all_event_builders_include_run_id_and_ts() -> None:
    run_id = "run1"
    assert events.scaffold_started(run_id, "bare")["run_id"] == run_id
    assert events.scaffold_phase(run_id, "bare", "phase")["run_id"] == run_id
    assert events.scaffold_delta(run_id, "bare", "d")["run_id"] == run_id
    assert events.scaffold_completed(run_id, "bare", "out", {})["run_id"] == run_id
    assert events.scaffold_failed(run_id, "bare", "err")["run_id"] == run_id
    assert events.evaluation_completed(run_id, "bare", 10, {}, {}, [])["run_id"] == run_id
    assert events.run_complete(run_id, "bare", {})["run_id"] == run_id
    assert events.heartbeat(run_id)["run_id"] == run_id
    assert events.comparison_started(run_id, [])["run_id"] == run_id
    assert events.case_started(run_id, "c1", "m1", "s1")["run_id"] == run_id
    assert events.case_delta(run_id, "c1", "d")["run_id"] == run_id
    assert events.case_completed(run_id, "c1", "out", {})["run_id"] == run_id
    assert events.case_evaluation_completed(run_id, "c1", 10, {})["run_id"] == run_id
    assert events.comparison_complete(run_id, {})["run_id"] == run_id
