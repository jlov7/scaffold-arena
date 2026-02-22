"""Model registry and pricing — single source of truth."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelDef:
    id: str
    label: str
    provider: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float


MODEL_REGISTRY: dict[str, ModelDef] = {
    "claude-sonnet-4-6": ModelDef(
        id="claude-sonnet-4-6",
        label="Claude Sonnet 4.6",
        provider="anthropic",
        input_usd_per_mtok=3.0,
        output_usd_per_mtok=15.0,
    ),
    "claude-haiku-4-5": ModelDef(
        id="claude-haiku-4-5",
        label="Claude Haiku 4.5",
        provider="anthropic",
        input_usd_per_mtok=1.0,
        output_usd_per_mtok=5.0,
    ),
    "gpt-4.1-mini": ModelDef(
        id="gpt-4.1-mini",
        label="GPT-4.1 mini",
        provider="openai",
        input_usd_per_mtok=0.4,
        output_usd_per_mtok=1.6,
    ),
    "gpt-4.1": ModelDef(
        id="gpt-4.1",
        label="GPT-4.1",
        provider="openai",
        input_usd_per_mtok=2.0,
        output_usd_per_mtok=8.0,
    ),
    "gemini-2.5-flash": ModelDef(
        id="gemini-2.5-flash",
        label="Gemini 2.5 Flash",
        provider="gemini",
        input_usd_per_mtok=0.3,
        output_usd_per_mtok=2.5,
    ),
    "gemini-2.5-pro": ModelDef(
        id="gemini-2.5-pro",
        label="Gemini 2.5 Pro",
        provider="gemini",
        input_usd_per_mtok=1.25,
        output_usd_per_mtok=10.0,
    ),
    "openrouter/openai/gpt-4.1-mini": ModelDef(
        id="openrouter/openai/gpt-4.1-mini",
        label="OpenRouter • GPT-4.1 mini",
        provider="openrouter",
        input_usd_per_mtok=0.5,
        output_usd_per_mtok=2.0,
    ),
    "openrouter/openai/gpt-4.1": ModelDef(
        id="openrouter/openai/gpt-4.1",
        label="OpenRouter • GPT-4.1",
        provider="openrouter",
        input_usd_per_mtok=2.5,
        output_usd_per_mtok=10.0,
    ),
}


def get_model(model_id: str) -> ModelDef:
    if model_id not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model: {model_id}")
    return MODEL_REGISTRY[model_id]


def cost_usd(input_tokens: int, output_tokens: int, model_id: str) -> float:
    m = get_model(model_id)
    return (input_tokens / 1_000_000) * m.input_usd_per_mtok + (
        output_tokens / 1_000_000
    ) * m.output_usd_per_mtok


def all_models_meta() -> list[dict]:
    return [
        {
            "id": m.id,
            "label": m.label,
            "provider": m.provider,
            "input_usd_per_mtok": m.input_usd_per_mtok,
            "output_usd_per_mtok": m.output_usd_per_mtok,
        }
        for m in MODEL_REGISTRY.values()
    ]
