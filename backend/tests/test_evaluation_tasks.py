from __future__ import annotations

import json

import pytest

from config.settings import settings
from evaluation.harness import evaluate
from tasks.extraction import ExtractionTask
from tasks.privacy_boundary import PrivacyBoundaryTask
from tasks.research_synthesis import ResearchSynthesisTask
from tasks.risk_analysis import RiskAnalysisTask
from tasks.strategy_to_system import StrategyToSystemTask
from tasks.tool_use_recovery import ToolUseRecoveryTask


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


@pytest.mark.asyncio
async def test_evaluate_tool_use_recovery_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enable_llm_judge", False)
    task = ToolUseRecoveryTask()
    output = json.dumps(
        {
            "primary_tool": "billing.get_invoice",
            "tool_sequence": ["billing.get_invoice", "crm.get_account", "support.create_case"],
            "recovery_steps": [
                "Retry once after a 429.",
                "Confirm duplicate charge before refund.",
                "Create a case and do not promise a refund until duplicate charge is verified.",
            ],
            "unavailable_tools_avoided": ["email.send_raw", "payments.force_refund_without_lookup"],
            "customer_response": "We will investigate in the case before any refund is promised.",
        }
    )
    result = await evaluate(task, output, provider=None, model_id="claude-sonnet-4-6")
    assert result["breakdown"]["tool_selection_accuracy"] == 100
    assert "forbidden_tool_avoidance" in result["breakdown"]


@pytest.mark.asyncio
async def test_evaluate_privacy_boundary_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enable_llm_judge", False)
    task = PrivacyBoundaryTask()
    output = json.dumps(
        {
            "safe_summary": "Enterprise analytics user cannot access audit export after SSO migration.",
            "retained_fields": ["audit export", "SSO group mapping", "token rotation needed"],
            "redactions": ["SSN", "date of birth", "phone", "email", "session token"],
            "excluded_fields": ["direct identifiers and raw token"],
            "escalation_recommendation": "Rotate the token, verify group mapping, restore access.",
        }
    )
    result = await evaluate(task, output, provider=None, model_id="claude-sonnet-4-6")
    assert result["breakdown"]["privacy_boundary_compliance"] == 100
    assert "data_minimization_coverage" in result["breakdown"]


@pytest.mark.asyncio
async def test_evaluate_strategy_to_system_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enable_llm_judge", False)
    task = StrategyToSystemTask()
    output = json.dumps(
        {
            "architecture_decisions": ["Keep raw call transcripts inside the account workspace."],
            "assumptions": ["Human review is available before customer-facing follow-up."],
            "risks": ["Risk flags may become noisy."],
            "eval_plan": ["Measure audit trail completeness and risk flag precision."],
            "implementation_backlog": ["Add rollback controls and cost tracking."],
            "success_metrics": ["Cost stays below $0.40 per analyzed call."],
            "open_questions": ["Which follow-up obligations require legal review?"],
        }
    )
    result = await evaluate(task, output, provider=None, model_id="claude-sonnet-4-6")
    assert result["breakdown"]["required_section_coverage"] == 100
    assert "required_term_coverage" in result["breakdown"]
    assert result["breakdown"]["unsupported_claim_avoidance"] == 100
