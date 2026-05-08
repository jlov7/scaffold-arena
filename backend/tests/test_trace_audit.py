from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit.trace_audit import (
    audit_records,
    audit_run_record,
    load_stored_run_records,
    load_trace_records,
    render_markdown_report,
)


def flawed_extraction_run() -> dict:
    return {
        "run_id": "run_audit_001",
        "kind": "arena",
        "task_id": "extraction",
        "model_id": "claude-sonnet-4-6",
        "scaffold_ids": ["bare", "plan_execute_verify"],
        "options": {"evaluation_profile": "strict"},
        "created_at": 1.0,
        "completed_at": 2.0,
        "winner_id": "bare",
        "status": "completed",
        "results": {
            "bare": {
                "output": '{"vendor_name":"Acme Corp"}',
                "metrics": {
                    "input_tokens": 1200,
                    "output_tokens": 360,
                    "cost_usd": 0,
                    "num_api_calls": 2,
                    "wall_time_ms": 1200,
                },
                "evaluation": {
                    "total_score": 42,
                    "breakdown": {
                        "schema_validity": 45,
                        "field_accuracy": 30,
                        "completeness": 20,
                    },
                    "notes": [
                        "Missing required fields: effective_date, renewal_term",
                        "Incorrect value: notice period",
                    ],
                },
            },
            "plan_execute_verify": {
                "output": '{"vendor_name":"Acme Corp","effective_date":"2026-01-01","renewal_term":"12 months"}',
                "metrics": {
                    "input_tokens": 1800,
                    "output_tokens": 520,
                    "cost_usd": 0.041,
                    "num_api_calls": 2,
                    "wall_time_ms": 1500,
                },
                "evaluation": {
                    "total_score": 88,
                    "breakdown": {
                        "schema_validity": 100,
                        "field_accuracy": 86,
                        "completeness": 82,
                    },
                    "notes": [],
                },
            },
        },
    }


def test_audit_run_record_classifies_integrity_cost_and_metric_failures() -> None:
    findings = audit_run_record(flawed_extraction_run())
    finding_types = {finding.type for finding in findings}

    assert "winner_not_highest_score" in finding_types
    assert "zero_cost_with_token_usage" in finding_types
    assert "schema_validity_low" in finding_types
    assert "extraction_wrong_values" in finding_types
    assert all(finding.regression_key for finding in findings)

    winner_finding = next(f for f in findings if f.type == "winner_not_highest_score")
    assert winner_finding.severity == "high"
    assert "bare" in winner_finding.evidence
    assert "plan_execute_verify" in winner_finding.evidence


def test_audit_records_renders_ranked_markdown_summary() -> None:
    report = audit_records([flawed_extraction_run()])
    markdown = render_markdown_report(report)

    assert report.run_count == 1
    assert report.scaffold_count == 2
    assert report.taxonomy_counts["winner_not_highest_score"] == 1
    assert report.severity_counts["high"] >= 1
    assert report.findings[0].severity in {"critical", "high"}
    assert "## Failure Taxonomy" in markdown
    assert "winner_not_highest_score" in markdown
    assert "run_audit_001" in markdown


def test_load_trace_records_accepts_single_run_and_run_list(tmp_path: Path) -> None:
    single_path = tmp_path / "single.json"
    single_path.write_text(json.dumps(flawed_extraction_run()))

    list_path = tmp_path / "list.json"
    list_path.write_text(json.dumps({"runs": [flawed_extraction_run()]}))

    assert [run["run_id"] for run in load_trace_records(single_path)] == ["run_audit_001"]
    assert [run["run_id"] for run in load_trace_records(list_path)] == ["run_audit_001"]


def test_load_stored_run_records_initializes_empty_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from config.settings import settings

    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "arena.db"))

    assert load_stored_run_records(limit=10) == []
