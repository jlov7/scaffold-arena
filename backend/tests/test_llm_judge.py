from __future__ import annotations

import pytest

from evaluation.llm_judge import run_judge
from tasks.extraction import ExtractionTask
from tasks.base import BaseTask


class FakeProvider:
    def __init__(self, text: str | None = None, error: Exception | None = None) -> None:
        self._text = text
        self._error = error

    async def complete(self, **kwargs):  # noqa: ANN003
        _ = kwargs
        if self._error:
            raise self._error
        return type("Result", (), {"text": self._text})


class UnknownTask(BaseTask):
    id = "unknown"
    name = "Unknown"
    subtitle = "Unknown"
    task_type = "unknown"
    synthetic_sources = False

    def get_input_text(self) -> str:
        return "input"

    def get_schema(self) -> dict:
        return {"type": "object"}

    def get_gold(self) -> dict:
        return {}


@pytest.mark.asyncio
async def test_judge_handles_missing_rubric() -> None:
    result = await run_judge(
        UnknownTask(),
        raw_output="{}",
        provider=FakeProvider("{}"),
        model_id="claude-sonnet-4-6",
    )
    assert result["scores"] == {}
    assert "No rubric defined" in result["explanation"]


@pytest.mark.asyncio
async def test_judge_parses_scores_and_explanation() -> None:
    payload = '{"scores":{"completeness":91,"reasoning_clarity":77},"explanation":"Looks good"}'
    result = await run_judge(
        ExtractionTask(),
        raw_output="{}",
        provider=FakeProvider(payload),
        model_id="claude-sonnet-4-6",
    )
    assert result["scores"]["completeness"] == 91
    assert result["explanation"] == "Looks good"


@pytest.mark.asyncio
async def test_judge_defaults_when_response_is_not_json() -> None:
    result = await run_judge(
        ExtractionTask(),
        raw_output="{}",
        provider=FakeProvider("not-json"),
        model_id="claude-sonnet-4-6",
    )
    assert result["scores"]["completeness"] == 50
    assert "could not be parsed" in result["explanation"]


@pytest.mark.asyncio
async def test_judge_returns_fallback_scores_on_provider_error() -> None:
    result = await run_judge(
        ExtractionTask(),
        raw_output="{}",
        provider=FakeProvider(error=RuntimeError("boom")),
        model_id="claude-sonnet-4-6",
    )
    assert result["scores"]["completeness"] == 50
    assert "Judge failed with error" in result["explanation"]
