from __future__ import annotations

import pytest

from evaluation.llm_judge import run_judge
from tasks.base import BaseTask
from tasks.extraction import ExtractionTask


class FakeProvider:
    def __init__(self, text: str | None = None, error: Exception | None = None) -> None:
        self._text = text
        self._error = error

    async def complete(self, **kwargs):
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
async def test_judge_extracts_a_fenced_json_object() -> None:
    payload = "Judge output:\n```json\n{\"scores\":{\"completeness\":91,\"reasoning_clarity\":77},\"explanation\":\"Looks good\"}\n```"
    result = await run_judge(
        ExtractionTask(), raw_output="{}", provider=FakeProvider(payload), model_id="claude-sonnet-4-6",
    )
    assert result["scores"] == {"completeness": 91, "reasoning_clarity": 77}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        '{"scores":{"completeness":101,"reasoning_clarity":77},"explanation":"bad"}',
        '{"scores":{"completeness":91},"explanation":"incomplete"}',
        '{"scores":{"completeness":true,"reasoning_clarity":77},"explanation":"bad"}',
        '{"scores":{"completeness":91,"reasoning_clarity":77},"explanation":null}',
    ],
)
async def test_judge_rejects_invalid_score_structure_conservatively(payload: str) -> None:
    result = await run_judge(
        ExtractionTask(), raw_output="{}", provider=FakeProvider(payload), model_id="claude-sonnet-4-6",
    )
    assert result["scores"] == {"completeness": 50, "reasoning_clarity": 50}
    assert "invalid score structure" in result["explanation"]


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
