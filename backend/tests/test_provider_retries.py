from __future__ import annotations

from dataclasses import dataclass

import pytest

from config.settings import settings
from core.provider import AnthropicProvider


class FakeStatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status={status_code}")
        self.status_code = status_code


@dataclass
class _Usage:
    input_tokens: int = 10
    output_tokens: int = 20


@dataclass
class _TextBlock:
    type: str = "text"
    text: str = "ok"


@dataclass
class _Response:
    content: list[_TextBlock]
    usage: _Usage


class FakeMessages:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = outcomes
        self.calls = 0

    async def create(self, **kwargs):
        _ = kwargs
        self.calls += 1
        outcome = self._outcomes[self.calls - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, messages: FakeMessages) -> None:
        self.messages = messages


@pytest.mark.asyncio
async def test_complete_retries_on_429_with_exponential_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "provider_max_retries", 3)
    monkeypatch.setattr(settings, "provider_retry_base_delay_ms", 10)

    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("core.provider.asyncio.sleep", _fake_sleep)

    provider = AnthropicProvider()
    messages = FakeMessages(
        [
            FakeStatusError(429),
            FakeStatusError(429),
            _Response(content=[_TextBlock(text="done")], usage=_Usage()),
        ]
    )
    provider._client = FakeClient(messages)  # type: ignore[assignment]

    result = await provider.complete(
        model_id="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "ping"}],
    )

    assert result.text == "done"
    assert messages.calls == 3
    assert sleeps == [0.01, 0.02]


@pytest.mark.asyncio
async def test_complete_retries_on_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "provider_max_retries", 3)
    monkeypatch.setattr(settings, "provider_retry_base_delay_ms", 10)

    async def _fake_sleep(delay: float) -> None:
        _ = delay

    monkeypatch.setattr("core.provider.asyncio.sleep", _fake_sleep)

    provider = AnthropicProvider()
    messages = FakeMessages(
        [
            FakeStatusError(503),
            _Response(content=[_TextBlock(text="recovered")], usage=_Usage()),
        ]
    )
    provider._client = FakeClient(messages)  # type: ignore[assignment]

    result = await provider.complete(
        model_id="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "ping"}],
    )
    assert result.text == "recovered"
    assert messages.calls == 2


@pytest.mark.asyncio
async def test_complete_fails_fast_on_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "provider_max_retries", 3)

    async def _fake_sleep(delay: float) -> None:
        _ = delay

    monkeypatch.setattr("core.provider.asyncio.sleep", _fake_sleep)

    provider = AnthropicProvider()
    messages = FakeMessages([FakeStatusError(401)])
    provider._client = FakeClient(messages)  # type: ignore[assignment]

    with pytest.raises(FakeStatusError):
        await provider.complete(
            model_id="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "ping"}],
        )
    assert messages.calls == 1


@pytest.mark.asyncio
async def test_complete_respects_max_retry_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "provider_max_retries", 1)
    monkeypatch.setattr(settings, "provider_retry_base_delay_ms", 10)

    async def _fake_sleep(delay: float) -> None:
        _ = delay

    monkeypatch.setattr("core.provider.asyncio.sleep", _fake_sleep)

    provider = AnthropicProvider()
    messages = FakeMessages([FakeStatusError(429), FakeStatusError(429)])
    provider._client = FakeClient(messages)  # type: ignore[assignment]

    with pytest.raises(FakeStatusError):
        await provider.complete(
            model_id="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "ping"}],
        )
    assert messages.calls == 2
