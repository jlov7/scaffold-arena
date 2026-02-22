import json

import pytest

from autopsy.analyzer import analyze_failures
from config.settings import settings
from core.registry import register_task
from evaluation.harness import WEIGHT_TABLES, evaluate
from report.markdown import generate_markdown
from tasks.extraction import ExtractionTask
from tasks.research_synthesis import ResearchSynthesisTask
from tasks.risk_analysis import RiskAnalysisTask


def _register_tasks() -> None:
    register_task(ExtractionTask())
    register_task(RiskAnalysisTask())
    register_task(ResearchSynthesisTask())


@pytest.mark.asyncio
async def test_evaluate_supports_all_task_type_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_tasks()
    monkeypatch.setattr(settings, "enable_llm_judge", False)

    assert set(WEIGHT_TABLES) == {"extraction", "risk", "research", "custom"}

    risk_output = json.dumps(
        {
            "risk_items": [],
            "overall_risk_score": 10,
            "top_3_priorities": ["a", "b", "c"],
            "negotiation_leverage_points": [],
        }
    )
    research_output = json.dumps(
        {
            "executive_summary": "summary",
            "key_findings": [],
            "synthesis": "synthesis",
            "recommendations": [],
            "source_reliability_notes": "notes",
        }
    )

    risk_eval = await evaluate(RiskAnalysisTask(), risk_output, provider=None, model_id="claude-sonnet-4-6")
    research_eval = await evaluate(
        ResearchSynthesisTask(),
        research_output,
        provider=None,
        model_id="claude-sonnet-4-6",
    )

    assert isinstance(risk_eval["total_score"], float)
    assert isinstance(research_eval["total_score"], float)


@pytest.mark.asyncio
async def test_autopsy_uses_risk_and_research_task_paths() -> None:
    _register_tasks()

    risk_output = json.dumps(
        {
            "risk_items": [],
            "overall_risk_score": 10,
            "top_3_priorities": ["a", "b", "c"],
            "negotiation_leverage_points": [],
        }
    )
    risk_result = await analyze_failures(
        task_id="risk",
        scaffold_id="bare",
        output=risk_output,
        evaluation={"breakdown": {"must_flag_hit_rate": 20, "false_positive_rate": 50}},
    )
    risk_failure_types = {f["type"] for f in risk_result["failures"]}
    assert "risk_missed_must_flag" in risk_failure_types
    assert "risk_false_positives_high" in risk_failure_types

    research_output = json.dumps(
        {
            "executive_summary": "summary",
            "key_findings": [],
            "synthesis": "synthesis",
            "recommendations": [],
            "source_reliability_notes": "notes",
        }
    )
    research_result = await analyze_failures(
        task_id="research",
        scaffold_id="bare",
        output=research_output,
        evaluation={
            "breakdown": {
                "citation_coverage": 40,
                "required_findings_coverage": 40,
            }
        },
    )
    research_failure_types = {f["type"] for f in research_result["failures"]}
    assert "research_missing_citations" in research_failure_types
    assert "research_missing_required_findings" in research_failure_types


def test_report_falls_back_for_unknown_ids() -> None:
    markdown = generate_markdown(
        task_id="unknown_task",
        model_id="unknown_model",
        results={},
    )
    assert "unknown_task" in markdown
    assert "unknown_model" in markdown


def test_report_uses_actual_judge_keys() -> None:
    _register_tasks()
    markdown = generate_markdown(
        task_id="extraction",
        model_id="claude-sonnet-4-6",
        results={
            "bare": {
                "metrics": {
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_usd": 0.001,
                    "wall_time_ms": 10,
                    "num_api_calls": 1,
                },
                "evaluation": {
                    "total_score": 88.0,
                    "breakdown": {},
                    "weights": {},
                    "notes": [],
                    "judge": {
                        "model_id": "claude-haiku-4-5",
                        "scores": {"completeness": 88},
                        "explanation": "Strong coverage.",
                    },
                },
            }
        },
    )
    assert "claude-haiku-4-5" in markdown
    assert "completeness" in markdown
    assert "Strong coverage." in markdown
