from __future__ import annotations

import json

from evaluation.deterministic import (
    citation_coverage,
    false_positive_rate,
    field_accuracy,
    must_flag_hit_rate,
    required_findings_coverage,
    risk_level_accuracy,
    schema_validity,
    structure_compliance,
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
