from __future__ import annotations

import json

import pytest

from config.settings import settings
from evaluation.harness import evaluate
from tasks.extraction import ExtractionTask
from tasks.research_synthesis import ResearchSynthesisTask
from tasks.risk_analysis import RiskAnalysisTask


@pytest.mark.asyncio
async def test_evaluate_extraction_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enable_llm_judge", False)
    task = ExtractionTask()
    output = json.dumps(task.get_gold())
    result = await evaluate(task, output, provider=None, model_id="claude-sonnet-4-6")
    assert "schema_validity" in result["breakdown"]
    assert "field_accuracy" in result["breakdown"]
    assert isinstance(result["total_score"], float)


@pytest.mark.asyncio
async def test_evaluate_risk_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enable_llm_judge", False)
    task = RiskAnalysisTask()
    output = json.dumps(
        {
            "risk_items": [],
            "overall_risk_score": 10,
            "top_3_priorities": ["a", "b", "c"],
            "negotiation_leverage_points": [],
        }
    )
    result = await evaluate(task, output, provider=None, model_id="claude-sonnet-4-6")
    assert "must_flag_hit_rate" in result["breakdown"]
    assert "risk_level_accuracy" in result["breakdown"]


@pytest.mark.asyncio
async def test_evaluate_research_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enable_llm_judge", False)
    task = ResearchSynthesisTask()
    output = json.dumps(
        {
            "executive_summary": "summary",
            "key_findings": [],
            "synthesis": "synthesis",
            "recommendations": [],
            "source_reliability_notes": "notes",
        }
    )
    result = await evaluate(task, output, provider=None, model_id="claude-sonnet-4-6")
    assert "citation_coverage" in result["breakdown"]
    assert "required_findings_coverage" in result["breakdown"]


@pytest.mark.asyncio
async def test_evaluation_profiles_shift_weight_toward_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enable_llm_judge", False)
    task = ExtractionTask()
    output = json.dumps(task.get_gold())

    balanced = await evaluate(
        task,
        output,
        provider=None,
        model_id="claude-sonnet-4-6",
        evaluation_profile="balanced",
    )
    strict = await evaluate(
        task,
        output,
        provider=None,
        model_id="claude-sonnet-4-6",
        evaluation_profile="strict",
    )
    cost_first = await evaluate(
        task,
        output,
        provider=None,
        model_id="claude-sonnet-4-6",
        evaluation_profile="cost_first",
    )

    def deterministic_share(result: dict) -> float:
        return sum(
            entry["weight"]
            for entry in result["weights"].values()
            if entry["type"] == "deterministic"
        )

    assert strict["profile"] == "strict"
    assert cost_first["profile"] == "cost_first"
    assert deterministic_share(strict) >= 0.7
    assert deterministic_share(cost_first) >= 0.7
    assert deterministic_share(strict) > deterministic_share(balanced)
    assert deterministic_share(cost_first) > deterministic_share(balanced)
