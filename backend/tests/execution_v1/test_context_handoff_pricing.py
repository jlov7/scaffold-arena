from __future__ import annotations

from adapters_v1.models import ProviderUsage
from execution_v1.pricing import CentralPriceResolver


def usage(**updates):
    value = ProviderUsage(evidence_source="provider_reported", input_tokens=12, output_tokens=3, total_tokens=15, context_tokens=12, tool_calls=0, cached_input_tokens=None, service_tier=None, billing_profile="local_zero_paid_context_handoff", provider_usage_digest="a" * 64)
    return value.model_copy(update=updates)


def test_exact_local_profile_prices_zero_without_fabricating_cache_telemetry() -> None:
    quote = CentralPriceResolver().resolve(provider="ollama", model_id="qwen3.5:4b", usage=usage())
    assert quote is not None and quote.cost_usd == 0.0
    assert CentralPriceResolver().resolve(provider="ollama", model_id="other", usage=usage()) is None
    assert CentralPriceResolver().resolve(provider="other", model_id="qwen3.5:4b", usage=usage()) is None
    assert CentralPriceResolver().resolve(provider="ollama", model_id="qwen3.5:4b", usage=usage(billing_profile="standard")) is None
