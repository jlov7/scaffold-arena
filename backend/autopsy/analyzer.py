"""Autopsy analyzer — classify failures and generate patches."""

from __future__ import annotations

import json

import jsonschema

from core.registry import get_task
from utils.json_extract import parse_json_lenient

FAILURE_TYPES = {
    "json_parse_failed": "Output could not be parsed as valid JSON",
    "schema_missing_required_fields": "JSON parsed but missing required schema fields",
    "schema_type_mismatch": "JSON parsed but field types don't match schema",
    "extraction_wrong_values": "Extraction values don't match expected gold answers",
    "risk_missed_must_flag": "Risk analysis missed must-flag clauses",
    "risk_false_positives_high": "Risk analysis flagged too many non-issues",
    "research_missing_citations": "Research synthesis missing required source citations",
    "research_missing_required_findings": "Research synthesis missing required findings",
}

_PATCHES: dict[str, dict] = {
    "json_parse_failed": {
        "output_constraints": {"force_json_only": True},
        "verify": {"enabled": True, "max_repairs": 1},
    },
    "schema_missing_required_fields": {
        "verify": {"enabled": True, "max_repairs": 1},
    },
    "schema_type_mismatch": {
        "verify": {"enabled": True, "max_repairs": 1},
    },
    "extraction_wrong_values": {
        "temperature": 0,
        "output_constraints": {"force_json_only": True},
    },
    "risk_missed_must_flag": {
        "system_prompt_addendum": "Pay special attention to ALL clauses that could represent legal or financial risk.",
    },
    "risk_false_positives_high": {
        "system_prompt_addendum": "Only flag items with clear legal/financial/operational risk. Avoid flagging standard clauses.",
    },
    "research_missing_citations": {
        "system_prompt_addendum": "You MUST reference ALL provided sources in your findings.",
    },
    "research_missing_required_findings": {
        "system_prompt_addendum": "Ensure you address ALL key themes across ALL sources.",
    },
}

_SEVERITY: dict[str, str] = {
    "json_parse_failed": "critical",
    "schema_missing_required_fields": "high",
    "schema_type_mismatch": "high",
    "extraction_wrong_values": "high",
    "risk_missed_must_flag": "high",
    "risk_false_positives_high": "medium",
    "research_missing_citations": "medium",
    "research_missing_required_findings": "high",
}


def _make_failure(failure_type: str, evidence: str) -> dict:
    return {
        "type": failure_type,
        "description": FAILURE_TYPES[failure_type],
        "severity": _SEVERITY[failure_type],
        "evidence": evidence,
    }


def _merge_patches(failure_types: list[str]) -> dict:
    merged: dict = {}
    for ft in failure_types:
        patch = _PATCHES.get(ft, {})
        for key, value in patch.items():
            if key not in merged:
                merged[key] = value
            elif isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = {**merged[key], **value}
            # scalars: first writer wins
    return merged


def _build_summary(failures: list[dict], patch: dict) -> str:
    if not failures:
        return "No failures identified. No patch required."

    count = len(failures)
    labels = ", ".join(f"{f['type']} ({f['severity']})" for f in failures)
    failure_sentence = f"Found {count} failure{'s' if count != 1 else ''}: {labels}."

    patch_notes: list[str] = []
    if patch.get("verify", {}).get("enabled"):
        repairs = patch["verify"].get("max_repairs", 1)
        patch_notes.append(f"enables verify loop with {repairs} repair attempt{'s' if repairs != 1 else ''}")
    if patch.get("output_constraints", {}).get("force_json_only"):
        patch_notes.append("forces JSON-only output")
    if "temperature" in patch:
        patch_notes.append(f"sets temperature to {patch['temperature']}")
    if "system_prompt_addendum" in patch:
        patch_notes.append("adds system prompt guidance")

    if patch_notes:
        patch_sentence = f"Patch {', '.join(patch_notes)}."
    else:
        patch_sentence = "No config changes in patch."

    return f"{failure_sentence} {patch_sentence}"


async def analyze_failures(
    task_id: str,
    scaffold_id: str,
    output: str,
    evaluation: dict,
    metrics: dict | None = None,
) -> dict:
    """Classify failures from a task run and generate a machine-applicable config patch."""
    task = get_task(task_id)
    schema = task.get_schema()

    failures: list[dict] = []

    # Step 1: attempt to parse output JSON
    parse_result = parse_json_lenient(output)

    if not parse_result.ok:
        failures.append(
            _make_failure(
                "json_parse_failed",
                f"Parse error: {parse_result.error}. Notes: {'; '.join(parse_result.notes)}",
            )
        )
    else:
        parsed = parse_result.data

        # Step 2: validate against schema
        try:
            jsonschema.validate(instance=parsed, schema=schema)
        except jsonschema.ValidationError as exc:
            # Distinguish missing required fields from type mismatches
            if exc.validator == "required":
                missing = exc.validator_value if isinstance(exc.validator_value, list) else [str(exc.validator_value)]
                failures.append(
                    _make_failure(
                        "schema_missing_required_fields",
                        f"Missing required fields: {', '.join(missing)}. {exc.message}",
                    )
                )
            elif exc.validator == "type":
                failures.append(
                    _make_failure(
                        "schema_type_mismatch",
                        f"Type mismatch at '{exc.json_path}': {exc.message}",
                    )
                )
            else:
                # Treat other schema violations as missing required fields by default
                failures.append(
                    _make_failure(
                        "schema_missing_required_fields",
                        f"Schema validation failed ({exc.validator}): {exc.message}",
                    )
                )

        # Step 3: task-type-specific score checks
        task_type = task.task_type
        breakdown: dict = evaluation.get("breakdown", {})

        if task_type == "extraction":
            field_accuracy = breakdown.get("field_accuracy", 100)
            if field_accuracy < 70:
                failures.append(
                    _make_failure(
                        "extraction_wrong_values",
                        f"field_accuracy={field_accuracy:.1f}% (threshold 70%)",
                    )
                )

        elif task_type == "risk_analysis":
            must_flag_hit_rate = breakdown.get("must_flag_hit_rate", 100)
            false_positive_rate = breakdown.get("false_positive_rate", 100)
            if must_flag_hit_rate < 70:
                failures.append(
                    _make_failure(
                        "risk_missed_must_flag",
                        f"must_flag_hit_rate={must_flag_hit_rate:.1f}% (threshold 70%)",
                    )
                )
            if false_positive_rate < 70:
                failures.append(
                    _make_failure(
                        "risk_false_positives_high",
                        f"false_positive_rate={false_positive_rate:.1f}% (threshold 70%)",
                    )
                )

        elif task_type == "research_synthesis":
            citation_coverage = breakdown.get("citation_coverage", 100)
            required_findings_coverage = breakdown.get("required_findings_coverage", 100)
            if citation_coverage < 70:
                failures.append(
                    _make_failure(
                        "research_missing_citations",
                        f"citation_coverage={citation_coverage:.1f}% (threshold 70%)",
                    )
                )
            if required_findings_coverage < 70:
                failures.append(
                    _make_failure(
                        "research_missing_required_findings",
                        f"required_findings_coverage={required_findings_coverage:.1f}% (threshold 70%)",
                    )
                )

    # Step 4: generate merged patch
    patch = _merge_patches([f["type"] for f in failures])

    # Step 5: build summary
    summary = _build_summary(failures, patch)

    return {
        "failures": failures,
        "patch": patch,
        "summary": summary,
    }
