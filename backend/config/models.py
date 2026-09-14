"""Versioned provider price catalogue and legacy model registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

PRICE_CATALOG_REVISION = "2026-08-14"
PRICE_CATALOG_EFFECTIVE_DATE = date(2026, 8, 14)
LOCAL_OLLAMA_CONTEXT_HANDOFF_PROFILE = "local_zero_paid_context_handoff"


@dataclass(frozen=True)
class BillingProfile:
    name: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    source_url: str
    min_context_tokens: int | None = None
    max_context_tokens: int | None = None

    def accepts_context(self, context_tokens: int | None) -> bool:
        if self.min_context_tokens is None and self.max_context_tokens is None:
            return True
        if context_tokens is None:
            return False
        return (self.min_context_tokens is None or context_tokens >= self.min_context_tokens) and (
            self.max_context_tokens is None or context_tokens <= self.max_context_tokens
        )


@dataclass(frozen=True)
class ModelDef:
    id: str
    label: str
    provider: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    catalog_revision: str = PRICE_CATALOG_REVISION
    effective_date: date = PRICE_CATALOG_EFFECTIVE_DATE
    source_url: str = ""
    billing_profile: str = "standard"


@dataclass(frozen=True)
class PriceCatalogEntry:
    provider: str
    model_id: str
    revision: str
    effective_date: date
    billing_profile: BillingProfile


ANTHROPIC_PRICING = "https://platform.claude.com/docs/en/about-claude/pricing"
OPENAI_GPT41_DOCS = "https://developers.openai.com/api/docs/models/gpt-4.1"
GEMINI_PRICING = "https://ai.google.dev/gemini-api/docs/pricing"
OPENROUTER_GPT41 = "https://openrouter.ai/openai/gpt-4.1"
OPENROUTER_GPT41_MINI = "https://openrouter.ai/openai/gpt-4.1-mini"

MODEL_REGISTRY: dict[str, ModelDef] = {
    "claude-sonnet-4-6": ModelDef("claude-sonnet-4-6", "Claude Sonnet 4.6", "anthropic", 3.0, 15.0, source_url=ANTHROPIC_PRICING),
    "claude-haiku-4-5": ModelDef("claude-haiku-4-5", "Claude Haiku 4.5", "anthropic", 1.0, 5.0, source_url=ANTHROPIC_PRICING),
    "gpt-4.1-mini": ModelDef("gpt-4.1-mini", "GPT-4.1 mini", "openai", 0.4, 1.6, source_url=OPENAI_GPT41_DOCS),
    "gpt-4.1": ModelDef("gpt-4.1", "GPT-4.1", "openai", 2.0, 8.0, source_url=OPENAI_GPT41_DOCS),
    "gemini-2.5-flash": ModelDef("gemini-2.5-flash", "Gemini 2.5 Flash", "gemini", 0.3, 2.5, source_url=GEMINI_PRICING),
    "gemini-2.5-pro": ModelDef("gemini-2.5-pro", "Gemini 2.5 Pro", "gemini", 1.25, 10.0, source_url=GEMINI_PRICING),
    "openrouter/openai/gpt-4.1-mini": ModelDef("openrouter/openai/gpt-4.1-mini", "OpenRouter • GPT-4.1 mini", "openrouter", 0.4, 1.6, source_url=OPENROUTER_GPT41_MINI),
    "openrouter/openai/gpt-4.1": ModelDef("openrouter/openai/gpt-4.1", "OpenRouter • GPT-4.1", "openrouter", 2.0, 8.0, source_url=OPENROUTER_GPT41),
}


def _entry(model: ModelDef, profile: BillingProfile) -> PriceCatalogEntry:
    return PriceCatalogEntry(model.provider, model.id, model.catalog_revision, model.effective_date, profile)


PRICE_CATALOG: tuple[PriceCatalogEntry, ...] = tuple(
    _entry(
        model,
        BillingProfile("standard", model.input_usd_per_mtok, model.output_usd_per_mtok, model.source_url),
    )
    for model in MODEL_REGISTRY.values() if model.id != "gemini-2.5-pro"
) + (
    PriceCatalogEntry(
        provider="ollama",
        model_id="qwen3.5:4b",
        revision="2026-09-13-context-handoff-local-v1",
        effective_date=date(2026, 9, 13),
        billing_profile=BillingProfile(
            LOCAL_OLLAMA_CONTEXT_HANDOFF_PROFILE, 0.0, 0.0,
            "local://scaffold-arena/context-handoff-local-v1/zero-paid-profile",
            max_context_tokens=4096,
        ),
    ),
    _entry(
        MODEL_REGISTRY["gemini-2.5-pro"],
        BillingProfile("standard", 1.25, 10.0, GEMINI_PRICING, max_context_tokens=200_000),
    ),
    _entry(
        MODEL_REGISTRY["gemini-2.5-pro"],
        BillingProfile("long_context", 2.5, 15.0, GEMINI_PRICING, min_context_tokens=200_001),
    ),
)


def get_model(model_id: str) -> ModelDef:
    if model_id not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model: {model_id}")
    return MODEL_REGISTRY[model_id]


def get_price_catalog_entry(*, provider: str, model_id: str, billing_profile: str = "standard") -> PriceCatalogEntry:
    matches = [
        entry for entry in PRICE_CATALOG
        if entry.provider == provider and entry.model_id == model_id and entry.billing_profile.name == billing_profile
    ]
    if len(matches) != 1:
        raise ValueError("no immutable price snapshot for provider, model, and billing profile")
    return matches[0]


def cost_usd(input_tokens: int, output_tokens: int, model_id: str) -> float:
    model = get_model(model_id)
    return (input_tokens / 1_000_000) * model.input_usd_per_mtok + (
        output_tokens / 1_000_000
    ) * model.output_usd_per_mtok


def all_models_meta() -> list[dict]:
    return [
        {
            "id": model.id,
            "label": model.label,
            "provider": model.provider,
            "input_usd_per_mtok": model.input_usd_per_mtok,
            "output_usd_per_mtok": model.output_usd_per_mtok,
            "price_catalog_revision": model.catalog_revision,
            "price_effective_date": model.effective_date.isoformat(),
            "price_source_url": model.source_url,
            "billing_profile": model.billing_profile,
        }
        for model in MODEL_REGISTRY.values()
    ]
