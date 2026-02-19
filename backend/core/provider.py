"""LLM provider abstraction wrapping the Anthropic SDK."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncGenerator

import anthropic

from config.settings import settings


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResult:
    text: str = ""
    usage: LLMUsage = field(default_factory=LLMUsage)


# Global semaphore for concurrent LLM call limiting
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.max_concurrent_llm_calls)
    return _semaphore


class AnthropicProvider:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def stream_text(
        self,
        model_id: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0,
        system: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream text deltas from the Anthropic API.

        Yields delta strings. After the generator is exhausted,
        call get_last_usage() to retrieve token counts.
        """
        sem = _get_semaphore()
        async with sem:
            kwargs: dict = {
                "model": model_id,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if system:
                kwargs["system"] = system

            async with self._client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text

                # After stream completes, store usage
                response = await stream.get_final_message()
                self._last_usage = LLMUsage(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )

    def get_last_usage(self) -> LLMUsage:
        return getattr(self, "_last_usage", LLMUsage())

    async def complete(
        self,
        model_id: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0,
        system: str | None = None,
    ) -> LLMResult:
        """Non-streaming completion. Returns full text + usage."""
        sem = _get_semaphore()
        async with sem:
            kwargs: dict = {
                "model": model_id,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if system:
                kwargs["system"] = system

            response = await self._client.messages.create(**kwargs)
            text = ""
            for block in response.content:
                if block.type == "text":
                    text += block.text
            return LLMResult(
                text=text,
                usage=LLMUsage(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                ),
            )
