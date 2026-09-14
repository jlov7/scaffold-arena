from __future__ import annotations

import json

from evaluation.deterministic import (
    citation_coverage,
    data_minimization_coverage,
    false_positive_rate,
    field_accuracy,
    forbidden_tool_avoidance,
    must_flag_hit_rate,
    privacy_boundary_compliance,
    recovery_step_coverage,
    required_findings_coverage,
    required_section_coverage,
    required_term_coverage,
    risk_level_accuracy,
    schema_validity,
    structure_compliance,
    tool_selection_accuracy,
    unsupported_claim_avoidance,
    word_count_compliance,
)
from tasks.extraction import ExtractionTask
from tasks.risk_analysis import RiskAnalysisTask


def test_schema_validity_success_and_failure() -> None:
    task = ExtractionTask()
    valid = schema_validity(json.dumps(task.get_gold()), task.get_schema())
    assert valid.score > 0

    invalid = schema_validity("not-json", task.get_schema())
    assert invalid.score == 0


def test_field_accuracy_scores_high_for_gold_output() -> None:
    task = ExtractionTask()
    result = field_accuracy(json.dumps(task.get_gold()), task.get_gold())
    assert result.score >= 95


def test_risk_metrics_paths() -> None:
    risk_output = json.dumps(
        {
            "risk_items": [
                {
                    "clause_number": "2",
                    "clause_title": "Data Handling",
                    "risk_level": "high",
                    "risk_description": "risk",
                    "specific_concern": "concern",
                    "recommendation": "recommendation",
                },
                {
                    "clause_number": "x",
                    "clause_title": "Noise",
                    "risk_level": "low",
                    "risk_description": "noise",
                    "specific_concern": "noise",
                    "recommendation": "noise",
                },
            ],
            "overall_risk_score": 10,
            "top_3_priorities": ["a", "b", "c"],
            "negotiation_leverage_points": [],
        }
    )
    gold = [{"clause": "2"}, {"clause": "3"}]
    hit = must_flag_hit_rate(risk_output, gold)
    assert hit.score == 50

    fp = false_positive_rate(risk_output)
    assert fp.score < 100

    levels = risk_level_accuracy(
        risk_output,
        [{"clause": "2", "risk_level": "high"}],
    )
    assert levels.score == 100

    schema = RiskAnalysisTask().get_schema()
    structure = structure_compliance(risk_output, schema)
    assert structure.score > 0


def test_research_metrics_paths() -> None:
    synthesis = " ".join(["word"] * 160)
    output = json.dumps(
        {
            "key_findings": [
                {
                    "finding": "orchestration failures",
                    "sources": ["A", "B"],
                    "confidence": "high",
                    "enterprise_implication": "important",
                }
            ],
            "synthesis": synthesis + " verification 23% memory 41% 3%",
        }
    )

    coverage = citation_coverage(output, ["A", "B", "SOURCE_C"])
    assert coverage.score < 100

    accidental_source_letters = citation_coverage(
        json.dumps(
            {
                "key_findings": [
                    {
                        "finding": "This paragraph contains ordinary alphabetic prose.",
                        "sources": [],
                        "confidence": "medium",
                        "enterprise_implication": "none",
                    }
                ],
                "synthesis": "A benchmark can be credible without burying source labels inside unrelated words.",
            }
        ),
        ["A", "B", "C", "D"],
    )
    assert accidental_source_letters.score == 25

    findings = required_findings_coverage(
        output,
        [
            {"keywords": ["verification", "23%"]},
            {"keywords": ["memory", "41%", "3%"]},
        ],
    )
    assert findings.score == 100

    wc = word_count_compliance(output)
    assert wc.score == 100

    wc_bad = word_count_compliance(json.dumps({"synthesis": "too short"}))
    assert wc_bad.score == 0


def test_tool_use_privacy_and_strategy_metrics_paths() -> None:
    tool_output = json.dumps(
        {
            "primary_tool": "billing.get_invoice",
            "tool_sequence": ["billing.get_invoice", "crm.get_account"],
            "recovery_steps": ["retry after 429", "confirm before refund"],
        }
    )
    tool_gold = {
        "required_tools": ["billing.get_invoice", "crm.get_account"],
        "forbidden_tools": ["email.send_raw"],
        "required_recovery_terms": ["retry", "429", "confirm"],
    }
    assert tool_selection_accuracy(tool_output, tool_gold).score == 100
    assert forbidden_tool_avoidance(tool_output, tool_gold).score == 100
    assert recovery_step_coverage(tool_output, tool_gold).score == 100

    privacy_output = json.dumps(
        {
            "safe_summary": "Audit export blocked after SSO migration. Rotate token.",
            "redactions": ["SSN", "phone"],
            "retained_fields": ["audit export", "SSO", "token"],
        }
    )
    privacy_gold = {
        "forbidden_terms": ["123-45-6789"],
        "required_retained_terms": ["audit export", "SSO", "token"],
        "required_redactions": ["SSN", "phone"],
    }
    assert privacy_boundary_compliance(privacy_output, privacy_gold).score == 100
    assert data_minimization_coverage(privacy_output, privacy_gold).score == 100

    strategy_output = json.dumps(
        {
            "architecture_decisions": ["Use audit trail"],
            "assumptions": ["Human review exists"],
            "risks": ["Rollback may be needed"],
        }
    )
    assert required_section_coverage(strategy_output, ["architecture_decisions", "risks"]).score == 100
    assert required_term_coverage(strategy_output, ["audit trail", "human review"]).score == 100
    assert unsupported_claim_avoidance(strategy_output, ["guaranteed"]).score == 100
    assert unsupported_claim_avoidance(
        json.dumps({"claim": "guaranteed 40% productivity lift"}),
        ["guaranteed 40% productivity"],
    ).score == 0
