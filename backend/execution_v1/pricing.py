"""Read-only central-price boundary for execution reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from adapters_v1.models import ProviderUsage
from config.models import LOCAL_OLLAMA_CONTEXT_HANDOFF_PROFILE, get_price_catalog_entry

from .currency import currency_float


@dataclass(frozen=True)
class PriceQuote:
    provider: str
    model_id: str
    price_catalog_revision: str
    provider_usage_digest: str
    cost_usd: float
    billing_profile: str = "standard"

    def __post_init__(self) -> None:
        if not self.provider or not self.model_id or not self.price_catalog_revision:
            raise ValueError("price quote requires provider, model, and central snapshot revision")
        if len(self.provider_usage_digest) != 64 or any(char not in "0123456789abcdef" for char in self.provider_usage_digest):
            raise ValueError("price quote requires a provider usage digest")
        normalized_cost = currency_float(self.cost_usd)
        if normalized_cost < 0:
            raise ValueError("price quote cost cannot be negative")
        object.__setattr__(self, "cost_usd", normalized_cost)


class PriceResolver(Protocol):
    """Resolves a central price snapshot without adapter-controlled prices."""

    def resolve(self, *, provider: str, model_id: str, usage: ProviderUsage) -> PriceQuote | None: ...


class CentralPriceResolver:
    """Prices only complete standard usage against an immutable catalogue row."""

    def resolve(self, *, provider: str, model_id: str, usage: ProviderUsage) -> PriceQuote | None:
        local_zero_paid = (
            provider == "ollama" and model_id == "qwen3.5:4b"
            and usage.billing_profile == LOCAL_OLLAMA_CONTEXT_HANDOFF_PROFILE
            and usage.cached_input_tokens is None and usage.service_tier is None
        )
        if (
            usage.input_tokens is None
            or usage.output_tokens is None
            or usage.provider_usage_digest is None
            or (usage.cached_input_tokens != 0 and not local_zero_paid)
            or usage.tool_billing_usd is not None
            or (usage.service_tier != "standard" and not local_zero_paid)
            or usage.billing_profile is None
        ):
            return None
        profile_name = usage.billing_profile
        try:
            entry = get_price_catalog_entry(
                provider=provider, model_id=model_id, billing_profile=profile_name,
            )
        except ValueError:
            return None
        if not entry.billing_profile.accepts_context(usage.context_tokens):
            return None
        profile = entry.billing_profile
        cost = currency_float(
            (
                Decimal(usage.input_tokens) * Decimal(str(profile.input_usd_per_mtok))
                + Decimal(usage.output_tokens) * Decimal(str(profile.output_usd_per_mtok))
            ) / Decimal(1_000_000)
        )
        return PriceQuote(
            provider=entry.provider,
            model_id=entry.model_id,
            price_catalog_revision=entry.revision,
            provider_usage_digest=usage.provider_usage_digest,
            cost_usd=cost,
            billing_profile=profile.name,
        )
