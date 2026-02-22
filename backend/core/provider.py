"""LLM provider abstraction with Anthropic, OpenAI, Gemini, and OpenRouter."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Protocol

import anthropic

from config.models import cost_usd, get_model
from config.settings import settings
from core.budget import budget_tracker, get_current_run_id

logger = logging.getLogger(__name__)


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResult:
    text: str = ""
    usage: LLMUsage = field(default_factory=LLMUsage)


class LLMProvider(Protocol):
    async def stream_text(
        self,
        model_id: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0,
        system: str | None = None,
    ) -> AsyncGenerator[str, None]: ...

    async def complete(
        self,
        model_id: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0,
        system: str | None = None,
    ) -> LLMResult: ...

    def get_last_usage(self) -> LLMUsage: ...


_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.max_concurrent_llm_calls)
    return _semaphore


class _RetryProviderMixin:
    @staticmethod
    def _status_code(exc: Exception) -> int | None:
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        response = getattr(exc, "response", None)
        code = getattr(response, "status_code", None)
        return code if isinstance(code, int) else None

    @classmethod
    def _retry_delay(cls, exc: Exception, attempt: int) -> float | None:
        status_code = cls._status_code(exc)
        if status_code == 401:
            return None

        retryable = status_code == 429 or (status_code is not None and 500 <= status_code <= 599)
        if not retryable:
            return None
        if attempt >= settings.provider_max_retries:
            return None

        base_delay_s = settings.provider_retry_base_delay_ms / 1000.0
        return base_delay_s * (2**attempt)


def _normalize_messages(
    messages: list[dict],
    system: str | None = None,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    if system:
        normalized.append({"role": "system", "content": system})
    for message in messages:
        role = str(message.get("role", "user"))
        content_raw = message.get("content", "")
        content = content_raw if isinstance(content_raw, str) else str(content_raw)
        normalized.append({"role": role, "content": content})
    return normalized


def _check_budget_pre_call(run_id: str | None) -> None:
    if not run_id:
        return
    budget_tracker.check_call_allowed(
        run_id=run_id,
        max_cost_per_run_usd=settings.max_cost_per_run_usd,
        daily_budget_usd=settings.daily_budget_usd,
    )


def _record_budget_post_call(run_id: str | None, model_id: str, usage: LLMUsage) -> None:
    if not run_id:
        return
    budget_tracker.record_spend(
        run_id=run_id,
        cost_usd=cost_usd(
            usage.input_tokens,
            usage.output_tokens,
            model_id,
        ),
    )


def _extract_openai_usage(usage: Any) -> LLMUsage:
    if usage is None:
        return LLMUsage()
    return LLMUsage(
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
    )


def _extract_openai_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
            else:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


class AnthropicProvider(_RetryProviderMixin):
    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or settings.anthropic_api_key
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for Anthropic models")
        self._client = anthropic.AsyncAnthropic(api_key=key)

    async def stream_text(
        self,
        model_id: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0,
        system: str | None = None,
    ) -> AsyncGenerator[str, None]:
        run_id = get_current_run_id()
        kwargs: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        sem = _get_semaphore()
        attempt = 0
        while True:
            yielded_any_delta = False
            try:
                _check_budget_pre_call(run_id)

                async with sem:
                    async with self._client.messages.stream(**kwargs) as stream:
                        async for text in stream.text_stream:
                            yielded_any_delta = True
                            yield text

                        response = await stream.get_final_message()
                        usage = LLMUsage(
                            input_tokens=response.usage.input_tokens,
                            output_tokens=response.usage.output_tokens,
                        )
                        self._last_usage = usage
                        _record_budget_post_call(run_id, model_id, usage)
                return
            except Exception as exc:
                delay = self._retry_delay(exc, attempt)
                if yielded_any_delta or delay is None:
                    raise
                logger.warning(
                    "Retrying Anthropic streaming call (attempt=%s, wait_s=%.3f, status=%s)",
                    attempt + 1,
                    delay,
                    self._status_code(exc),
                )
                attempt += 1
                await asyncio.sleep(delay)

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
        run_id = get_current_run_id()
        kwargs: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        sem = _get_semaphore()
        attempt = 0
        while True:
            try:
                _check_budget_pre_call(run_id)

                async with sem:
                    response = await self._client.messages.create(**kwargs)

                text = ""
                for block in response.content:
                    if block.type == "text":
                        text += block.text

                usage = LLMUsage(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )
                result = LLMResult(text=text, usage=usage)
                _record_budget_post_call(run_id, model_id, usage)
                return result
            except Exception as exc:
                delay = self._retry_delay(exc, attempt)
                if delay is None:
                    raise
                logger.warning(
                    "Retrying Anthropic completion call (attempt=%s, wait_s=%.3f, status=%s)",
                    attempt + 1,
                    delay,
                    self._status_code(exc),
                )
                attempt += 1
                await asyncio.sleep(delay)


class _OpenAICompatibleProvider(_RetryProviderMixin):
    def __init__(
        self,
        *,
        api_key: str,
        missing_key_message: str,
        base_url: str | None = None,
        default_headers: dict[str, str] | None = None,
        provider_name: str = "OpenAI-compatible",
        api_key_override: str | None = None,
    ) -> None:
        effective_key = api_key_override or api_key
        if not effective_key:
            raise RuntimeError(missing_key_message)
        try:
            from openai import AsyncOpenAI  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised in runtime envs
            raise RuntimeError(
                "openai package is required for OpenAI-compatible providers. Run: uv add openai"
            ) from exc

        client_kwargs: dict[str, Any] = {"api_key": effective_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        if default_headers:
            client_kwargs["default_headers"] = default_headers

        self._client = AsyncOpenAI(**client_kwargs)
        self._last_usage = LLMUsage()
        self._provider_name = provider_name

    def _resolve_model_id(self, model_id: str) -> str:
        return model_id

    async def stream_text(
        self,
        model_id: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0,
        system: str | None = None,
    ) -> AsyncGenerator[str, None]:
        run_id = get_current_run_id()
        kwargs: dict[str, Any] = {
            "model": self._resolve_model_id(model_id),
            "messages": _normalize_messages(messages, system=system),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        sem = _get_semaphore()
        attempt = 0
        while True:
            yielded_any_delta = False
            try:
                _check_budget_pre_call(run_id)

                usage = LLMUsage()
                async with sem:
                    stream = await self._client.chat.completions.create(**kwargs)
                    async for chunk in stream:
                        chunk_usage = getattr(chunk, "usage", None)
                        if chunk_usage:
                            usage = _extract_openai_usage(chunk_usage)
                        choice = chunk.choices[0] if chunk.choices else None
                        delta = getattr(getattr(choice, "delta", None), "content", None)
                        if isinstance(delta, str) and delta:
                            yielded_any_delta = True
                            yield delta

                self._last_usage = usage
                _record_budget_post_call(run_id, model_id, usage)
                return
            except Exception as exc:
                delay = self._retry_delay(exc, attempt)
                if yielded_any_delta or delay is None:
                    raise
                logger.warning(
                    "Retrying %s streaming call (attempt=%s, wait_s=%.3f, status=%s)",
                    self._provider_name,
                    attempt + 1,
                    delay,
                    self._status_code(exc),
                )
                attempt += 1
                await asyncio.sleep(delay)

    def get_last_usage(self) -> LLMUsage:
        return self._last_usage

    async def complete(
        self,
        model_id: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0,
        system: str | None = None,
    ) -> LLMResult:
        run_id = get_current_run_id()
        kwargs: dict[str, Any] = {
            "model": self._resolve_model_id(model_id),
            "messages": _normalize_messages(messages, system=system),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        sem = _get_semaphore()
        attempt = 0
        while True:
            try:
                _check_budget_pre_call(run_id)

                async with sem:
                    response = await self._client.chat.completions.create(**kwargs)

                content = response.choices[0].message.content if response.choices else ""
                text = _extract_openai_text(content)
                usage = _extract_openai_usage(getattr(response, "usage", None))
                self._last_usage = usage
                result = LLMResult(text=text, usage=usage)
                _record_budget_post_call(run_id, model_id, usage)
                return result
            except Exception as exc:
                delay = self._retry_delay(exc, attempt)
                if delay is None:
                    raise
                logger.warning(
                    "Retrying %s completion call (attempt=%s, wait_s=%.3f, status=%s)",
                    self._provider_name,
                    attempt + 1,
                    delay,
                    self._status_code(exc),
                )
                attempt += 1
                await asyncio.sleep(delay)


class OpenAIProvider(_OpenAICompatibleProvider):
    def __init__(self, api_key_override: str | None = None) -> None:
        super().__init__(
            api_key=settings.openai_api_key,
            missing_key_message="OPENAI_API_KEY is required for OpenAI models",
            provider_name="OpenAI",
            api_key_override=api_key_override,
        )


class GeminiProvider(_OpenAICompatibleProvider):
    def __init__(self, api_key_override: str | None = None) -> None:
        super().__init__(
            api_key=settings.gemini_api_key,
            missing_key_message="GEMINI_API_KEY is required for Gemini models",
            base_url=settings.gemini_openai_base_url,
            provider_name="Gemini",
            api_key_override=api_key_override,
        )


class OpenRouterProvider(_OpenAICompatibleProvider):
    def __init__(self, api_key_override: str | None = None) -> None:
        headers: dict[str, str] = {}
        if settings.openrouter_site_url:
            headers["HTTP-Referer"] = settings.openrouter_site_url
        if settings.openrouter_app_name:
            headers["X-Title"] = settings.openrouter_app_name

        super().__init__(
            api_key=settings.openrouter_api_key,
            missing_key_message="OPENROUTER_API_KEY is required for OpenRouter models",
            base_url=settings.openrouter_base_url,
            default_headers=headers or None,
            provider_name="OpenRouter",
            api_key_override=api_key_override,
        )

    def _resolve_model_id(self, model_id: str) -> str:
        prefix = "openrouter/"
        if model_id.startswith(prefix):
            return model_id[len(prefix) :]
        return model_id


def get_provider(model_id: str, api_key_override: str | None = None) -> LLMProvider:
    provider_name = get_model(model_id).provider
    if provider_name == "anthropic":
        return AnthropicProvider(api_key=api_key_override)
    if provider_name == "openai":
        return OpenAIProvider(api_key_override=api_key_override)
    if provider_name == "gemini":
        return GeminiProvider(api_key_override=api_key_override)
    if provider_name == "openrouter":
        return OpenRouterProvider(api_key_override=api_key_override)
    raise ValueError(f"Unsupported provider '{provider_name}' for model '{model_id}'")
