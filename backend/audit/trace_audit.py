from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

Severity = Literal["critical", "high", "medium", "low", "info"]

SEVERITY_RANK: dict[str, int] = {
    "critical": 5,
    "high": 4,
    "medium": 3,
    "low": 2,
    "info": 1,
}

TASK_METRIC_FINDINGS: dict[str, tuple[str, str]] = {
    "schema_validity": (
        "schema_validity_low",
        "Treat schema validity as a blocking regression before trusting downstream scoring.",
    ),
    "field_accuracy": (
        "extraction_wrong_values",
        "Add or update an extraction regression case that checks the missed field values.",
    ),
    "must_flag_hit_rate": (
        "risk_missed_must_flag",
        "Add a risk-analysis regression covering each missed must-flag clause.",
    ),
    "risk_level_accuracy": (
        "risk_level_mismatch",
        "Add a risk-level calibration regression for this task family.",
    ),
    "false_positive_rate": (
        "risk_false_positives_high",
        "Review false-positive clauses and add a negative-control regression.",
    ),
    "citation_coverage": (
        "research_missing_citations",
        "Add a research-synthesis regression that requires source-backed claims.",
    ),
    "required_findings_coverage": (
        "research_missing_required_findings",
        "Add a research-synthesis regression for the missing required findings.",
    ),
    "word_count_compliance": (
        "research_word_count_noncompliance",
        "Add output-length checks to the rerun fixture for this task.",
    ),
}


@dataclass(frozen=True)
class TraceFinding:
    type: str
    severity: Severity
    run_id: str
    evidence: str
    recommendation: str
    regression_key: str
    task_id: str | None = None
    model_id: str | None = None
    scaffold_id: str | None = None
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TraceAuditReport:
    run_count: int
    scaffold_count: int
    finding_count: int
    severity_counts: dict[str, int]
    taxonomy_counts: dict[str, int]
    findings: list[TraceFinding]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_count": self.run_count,
            "scaffold_count": self.scaffold_count,
            "finding_count": self.finding_count,
            "severity_counts": self.severity_counts,
            "taxonomy_counts": self.taxonomy_counts,
            "findings": [finding.to_dict() for finding in self.findings],
        }


def audit_run_record(record: dict[str, Any]) -> list[TraceFinding]:
    run_id = str(record.get("run_id") or "unknown_run")
    task_id = _optional_str(record.get("task_id"))
    model_id = _optional_str(record.get("model_id"))
    winner_id = _optional_str(record.get("winner_id"))
    status = _optional_str(record.get("status"))
    results = record.get("results")
    findings: list[TraceFinding] = []

    if not isinstance(results, dict) or not results:
        findings.append(
            _finding(
                "no_scaffold_results",
                "critical",
                run_id,
                task_id,
                model_id,
                None,
                "Run has no scaffold results to evaluate.",
                "Reproduce the run and inspect lifecycle/SSE persistence before scoring quality.",
            )
        )
        return _sort_findings(findings)

    scored_results = {
        scaffold_id: score
        for scaffold_id, result in results.items()
        if isinstance(scaffold_id, str)
        if (score := _result_score(result)) is not None
    }
    if status == "completed" and scored_results and not winner_id:
        findings.append(
            _finding(
                "missing_winner",
                "high",
                run_id,
                task_id,
                model_id,
                None,
                "Completed run has scored scaffold results but no winner_id.",
                "Add a regression that asserts winner selection is persisted for completed runs.",
            )
        )
    elif winner_id and winner_id not in results:
        findings.append(
            _finding(
                "winner_missing_result",
                "high",
                run_id,
                task_id,
                model_id,
                winner_id,
                f"winner_id '{winner_id}' does not match any scaffold result.",
                "Guard winner selection against stale scaffold ids before persisting the run.",
            )
        )
    elif winner_id and winner_id in scored_results:
        best_scaffold_id, best_score = max(scored_results.items(), key=lambda item: item[1])
        winner_score = scored_results[winner_id]
        if best_scaffold_id != winner_id and best_score - winner_score > 0.1:
            findings.append(
                _finding(
                    "winner_not_highest_score",
                    "high",
                    run_id,
                    task_id,
                    model_id,
                    winner_id,
                    (
                        f"Winner {winner_id} scored {_fmt_score(winner_score)}, "
                        f"but {best_scaffold_id} scored {_fmt_score(best_score)}."
                    ),
                    "Add a winner-selection regression using this run as a fixture.",
                    score=winner_score,
                )
            )

    for scaffold_id, result in results.items():
        findings.extend(
            _audit_scaffold_result(
                run_id=run_id,
                task_id=task_id,
                model_id=model_id,
                scaffold_id=str(scaffold_id),
                result=result,
                winner_id=winner_id,
            )
        )

    return _sort_findings(findings)


def audit_records(records: Iterable[dict[str, Any]]) -> TraceAuditReport:
    record_list = list(records)
    findings = _sort_findings(finding for record in record_list for finding in audit_run_record(record))
    severity_counts = Counter(finding.severity for finding in findings)
    taxonomy_counts = Counter(finding.type for finding in findings)
    scaffold_count = sum(
        len(record.get("results", {}))
        for record in record_list
        if isinstance(record.get("results"), dict)
    )
    return TraceAuditReport(
        run_count=len(record_list),
        scaffold_count=scaffold_count,
        finding_count=len(findings),
        severity_counts={key: severity_counts.get(key, 0) for key in SEVERITY_RANK},
        taxonomy_counts=dict(sorted(taxonomy_counts.items())),
        findings=findings,
    )


def load_trace_records(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text())
    if isinstance(data, list):
        return _validate_records(data)
    if isinstance(data, dict) and isinstance(data.get("runs"), list):
        return _validate_records(data["runs"])
    if isinstance(data, dict) and "run_id" in data:
        return [data]
    raise ValueError("Trace input must be a run record, a list of run records, or an object with a runs list.")


def load_stored_run_records(limit: int = 100) -> list[dict[str, Any]]:
    from core.storage import init_db, list_runs

    init_db()
    return list_runs(limit=limit)


def render_markdown_report(report: TraceAuditReport) -> str:
    lines = [
        "# Trace-Driven Frontier Audit",
        "",
        "## Summary",
        "",
        f"- Runs audited: {report.run_count}",
        f"- Scaffold results audited: {report.scaffold_count}",
        f"- Findings: {report.finding_count}",
        "",
        "## Severity Summary",
        "",
        "| Severity | Count |",
        "| --- | ---: |",
    ]
    for severity in SEVERITY_RANK:
        lines.append(f"| {severity} | {report.severity_counts.get(severity, 0)} |")

    lines.extend(["", "## Failure Taxonomy", "", "| Type | Count |", "| --- | ---: |"])
    if report.taxonomy_counts:
        for finding_type, count in sorted(report.taxonomy_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| `{finding_type}` | {count} |")
    else:
        lines.append("| None | 0 |")

    lines.extend(["", "## Findings", ""])
    if not report.findings:
        lines.append("No findings.")
        return "\n".join(lines) + "\n"

    for finding in report.findings:
        scope = finding.run_id
        if finding.scaffold_id:
            scope = f"{scope} / {finding.scaffold_id}"
        lines.extend(
            [
                f"### [{finding.severity.upper()}] `{finding.type}`",
                "",
                f"- Scope: `{scope}`",
                f"- Task: `{finding.task_id or 'unknown'}`",
                f"- Model: `{finding.model_id or 'unknown'}`",
                f"- Evidence: {finding.evidence}",
                f"- Recommendation: {finding.recommendation}",
                f"- Regression key: `{finding.regression_key}`",
                "",
            ]
        )

    return "\n".join(lines)


def _audit_scaffold_result(
    *,
    run_id: str,
    task_id: str | None,
    model_id: str | None,
    scaffold_id: str,
    result: Any,
    winner_id: str | None,
) -> list[TraceFinding]:
    findings: list[TraceFinding] = []
    if not isinstance(result, dict):
        return [
            _finding(
                "invalid_result_shape",
                "critical",
                run_id,
                task_id,
                model_id,
                scaffold_id,
                f"Scaffold result is {type(result).__name__}, expected object.",
                "Fix result serialization before using this run as evidence.",
            )
        ]

    error = result.get("error")
    output = result.get("output")
    evaluation = result.get("evaluation")
    metrics = result.get("metrics")

    if error:
        findings.append(
            _finding(
                "scaffold_provider_error",
                "high",
                run_id,
                task_id,
                model_id,
                scaffold_id,
                f"Scaffold failed with error: {_shorten(str(error))}",
                "Capture this provider/runtime failure as a lifecycle regression.",
            )
        )
    if not output and not error:
        findings.append(
            _finding(
                "missing_output",
                "high",
                run_id,
                task_id,
                model_id,
                scaffold_id,
                "Scaffold result has no output and no explicit error.",
                "Add a lifecycle regression that requires either output or a typed failure envelope.",
            )
        )
    if output and not isinstance(evaluation, dict):
        findings.append(
            _finding(
                "missing_evaluation",
                "high",
                run_id,
                task_id,
                model_id,
                scaffold_id,
                "Scaffold produced output but has no evaluation object.",
                "Block report/export readiness until every completed scaffold has an evaluation.",
            )
        )

    findings.extend(_audit_metrics(run_id, task_id, model_id, scaffold_id, metrics))
    if isinstance(evaluation, dict):
        findings.extend(_audit_evaluation(run_id, task_id, model_id, scaffold_id, evaluation, winner_id))

    return findings


def _audit_metrics(
    run_id: str,
    task_id: str | None,
    model_id: str | None,
    scaffold_id: str,
    metrics: Any,
) -> list[TraceFinding]:
    if not isinstance(metrics, dict):
        return [
            _finding(
                "missing_metrics",
                "medium",
                run_id,
                task_id,
                model_id,
                scaffold_id,
                "Scaffold result has no metrics object.",
                "Persist token, cost, call-count, and timing metrics for every scaffold result.",
            )
        ]

    input_tokens = _number(metrics.get("input_tokens")) or 0
    output_tokens = _number(metrics.get("output_tokens")) or 0
    total_tokens = _number(metrics.get("total_tokens"))
    tokens = total_tokens if total_tokens is not None else input_tokens + output_tokens
    cost = _number(metrics.get("cost_usd"))
    api_calls = _number(metrics.get("num_api_calls") or metrics.get("api_calls")) or 0
    findings: list[TraceFinding] = []

    if tokens > 0 and (cost is None or cost <= 0):
        findings.append(
            _finding(
                "zero_cost_with_token_usage",
                "high",
                run_id,
                task_id,
                model_id,
                scaffold_id,
                f"Metrics show {_fmt_score(tokens)} tokens but cost_usd is {cost!r}.",
                "Recompute cost from provider usage via the centralized model price table.",
            )
        )
    if api_calls > 0 and tokens <= 0:
        findings.append(
            _finding(
                "missing_token_usage",
                "high",
                run_id,
                task_id,
                model_id,
                scaffold_id,
                f"Metrics show {_fmt_score(api_calls)} API calls but no token usage.",
                "Persist provider usage fields before calculating costs or declaring savings.",
            )
        )
    return findings


def _audit_evaluation(
    run_id: str,
    task_id: str | None,
    model_id: str | None,
    scaffold_id: str,
    evaluation: dict[str, Any],
    winner_id: str | None,
) -> list[TraceFinding]:
    findings: list[TraceFinding] = []
    score = _number(evaluation.get("total_score"))
    if score is None:
        findings.append(
            _finding(
                "missing_total_score",
                "medium",
                run_id,
                task_id,
                model_id,
                scaffold_id,
                "Evaluation object has no numeric total_score.",
                "Require numeric total_score before winner selection and report export.",
            )
        )
    else:
        if score < 30:
            severity: Severity = "critical"
        elif score < 50:
            severity = "high"
        elif score < 70:
            severity = "medium"
        else:
            severity = "info"
        if score < 70:
            findings.append(
                _finding(
                    "low_total_score",
                    severity,
                    run_id,
                    task_id,
                    model_id,
                    scaffold_id,
                    f"Evaluation total_score is {_fmt_score(score)}.",
                    "Queue autopsy, patch, and rerun before treating this scaffold as production evidence.",
                    score=score,
                )
            )
        if score < 70 and scaffold_id != winner_id:
            findings.append(
                _finding(
                    "patch_rerun_candidate",
                    "medium",
                    run_id,
                    task_id,
                    model_id,
                    scaffold_id,
                    f"Non-winning scaffold scored {_fmt_score(score)} and is a direct patch-rerun candidate.",
                    "Use this trace to create a focused autopsy-to-patch regression.",
                    score=score,
                )
            )

    breakdown = evaluation.get("breakdown")
    if isinstance(breakdown, dict):
        findings.extend(_audit_metric_breakdown(run_id, task_id, model_id, scaffold_id, breakdown))

    notes = evaluation.get("notes")
    if isinstance(notes, list):
        findings.extend(_audit_notes(run_id, task_id, model_id, scaffold_id, notes))

    return findings


def _audit_metric_breakdown(
    run_id: str,
    task_id: str | None,
    model_id: str | None,
    scaffold_id: str,
    breakdown: dict[str, Any],
) -> list[TraceFinding]:
    findings: list[TraceFinding] = []
    for metric_id, (finding_type, recommendation) in TASK_METRIC_FINDINGS.items():
        value = _number(breakdown.get(metric_id))
        if value is None or value >= 70:
            continue
        severity: Severity = "critical" if value < 25 else "high"
        findings.append(
            _finding(
                finding_type,
                severity,
                run_id,
                task_id,
                model_id,
                scaffold_id,
                f"Metric {metric_id} scored {_fmt_score(value)}.",
                recommendation,
                score=value,
            )
        )
    return findings


def _audit_notes(
    run_id: str,
    task_id: str | None,
    model_id: str | None,
    scaffold_id: str,
    notes: list[Any],
) -> list[TraceFinding]:
    joined = " ".join(str(note) for note in notes).lower()
    findings: list[TraceFinding] = []
    if "missing required" in joined:
        findings.append(
            _finding(
                "schema_missing_required_fields",
                "high",
                run_id,
                task_id,
                model_id,
                scaffold_id,
                f"Evaluation notes mention missing required fields: {_shorten('; '.join(map(str, notes)))}",
                "Promote this note into a fixture-level schema regression.",
            )
        )
    if "citation" in joined and ("missing" in joined or "no " in joined):
        findings.append(
            _finding(
                "research_missing_citations",
                "high",
                run_id,
                task_id,
                model_id,
                scaffold_id,
                f"Evaluation notes mention citation gaps: {_shorten('; '.join(map(str, notes)))}",
                "Require source-backed claims in the research regression fixture.",
            )
        )
    return findings


def _finding(
    finding_type: str,
    severity: Severity,
    run_id: str,
    task_id: str | None,
    model_id: str | None,
    scaffold_id: str | None,
    evidence: str,
    recommendation: str,
    *,
    score: float | None = None,
) -> TraceFinding:
    return TraceFinding(
        type=finding_type,
        severity=severity,
        run_id=run_id,
        task_id=task_id,
        model_id=model_id,
        scaffold_id=scaffold_id,
        evidence=evidence,
        recommendation=recommendation,
        regression_key=_regression_key(task_id, scaffold_id, finding_type),
        score=score,
    )


def _sort_findings(findings: Iterable[TraceFinding]) -> list[TraceFinding]:
    merged_findings = _merge_duplicate_findings(findings)
    return sorted(
        merged_findings,
        key=lambda finding: (
            -SEVERITY_RANK[finding.severity],
            finding.run_id,
            finding.scaffold_id or "",
            finding.type,
        ),
    )


def _merge_duplicate_findings(findings: Iterable[TraceFinding]) -> list[TraceFinding]:
    merged: dict[tuple[str, str | None, str, str], TraceFinding] = {}
    for finding in findings:
        key = (finding.run_id, finding.scaffold_id, finding.type, finding.regression_key)
        existing = merged.get(key)
        if existing is None:
            merged[key] = finding
            continue

        primary = existing
        if SEVERITY_RANK[finding.severity] > SEVERITY_RANK[existing.severity]:
            primary = finding
        merged[key] = TraceFinding(
            type=primary.type,
            severity=primary.severity,
            run_id=primary.run_id,
            task_id=primary.task_id,
            model_id=primary.model_id,
            scaffold_id=primary.scaffold_id,
            evidence=_join_unique(existing.evidence, finding.evidence),
            recommendation=_join_unique(existing.recommendation, finding.recommendation),
            regression_key=primary.regression_key,
            score=primary.score if primary.score is not None else existing.score,
        )
    return list(merged.values())


def _join_unique(first: str, second: str) -> str:
    if first == second:
        return first
    return f"{first} {second}"


def _validate_records(records: list[Any]) -> list[dict[str, Any]]:
    if not all(isinstance(record, dict) for record in records):
        raise ValueError("Every trace record must be an object.")
    return records


def _result_score(result: Any) -> float | None:
    if not isinstance(result, dict):
        return None
    evaluation = result.get("evaluation")
    if not isinstance(evaluation, dict):
        return None
    return _number(evaluation.get("total_score"))


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _regression_key(task_id: str | None, scaffold_id: str | None, finding_type: str) -> str:
    parts = [task_id or "unknown_task", scaffold_id or "run", finding_type]
    return ".".join(_slug(part) for part in parts)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "unknown"


def _fmt_score(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _shorten(value: str, max_length: int = 180) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3] + "..."
