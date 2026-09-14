#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "outputs/benchmark_runs"
SCENARIO_PACK_PATH = ROOT / "docs/benchmarking/scenario_pack_v0.1.json"
ANNOTATION_SCHEMA_PATH = ROOT / "specs/v1/review-v1-calibration-annotation-result.schema.json"
ADJUDICATION_SCHEMA_PATH = ROOT / "specs/v1/review-v1-calibration-adjudication-result.schema.json"
EXTERNAL_LEDGER_PATH = ROOT / "outputs/external_validation.json"
PACKET_PATH = ROOT / "outputs/human_calibration_packet.json"
AUDIT_PATH = ROOT / "outputs/human_calibration_audit.json"

ANNOTATION_DIMENSIONS = (
    "task_success",
    "evidence_grounding",
    "schema_adherence",
    "safety_boundary",
    "actionability",
)
ASSIGNED_PSEUDONYMS = ("annotator-01", "annotator-02", "annotator-03")
CONFLICT_THRESHOLD = 0.20


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _scenario_index() -> dict[str, dict[str, Any]]:
    pack = _load_json(SCENARIO_PACK_PATH)
    return {
        str(scenario["scenario_id"]): scenario
        for scenario in pack.get("scenarios", [])
        if isinstance(scenario, dict)
    }


def _selected_runs() -> list[dict[str, Any]]:
    runs = []
    for path in sorted(RUN_DIR.glob("*.json")):
        artifact = _load_json(path)
        if str(artifact.get("run_id", "")).endswith("_r1"):
            runs.append(artifact)
    return sorted(runs, key=lambda run: (str(run.get("task_family")), str(run.get("scenario_id"))))


def _annotation_target(run: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    target_id = f"annotate_{run['run_id']}"
    annotator_view = {
        "scenario_name": scenario["name"],
        "prompt": scenario["prompt"],
        "output_schema": scenario["output_schema"],
        "evidence_requirements": scenario["evidence_requirements"],
        "allowed_claims": scenario["allowed_claims"],
        "limitations": scenario["limitations"],
        "model_id": run["model_id"],
        "output": run["output"],
    }
    return {
        "target_id": target_id,
        "run_id": run["run_id"],
        "scenario_id": run["scenario_id"],
        "task_family": run["task_family"],
        "mode": run["mode"],
        "annotator_view": annotator_view,
        "blind_payload_digest": _digest(annotator_view),
        "assignments": [
            {
                "assignment_id": _digest({"target_id": target_id, "annotator_pseudonym": pseudonym})[:24],
                "annotator_pseudonym": pseudonym,
            }
            for pseudonym in ASSIGNED_PSEUDONYMS
        ],
        "withheld_from_annotator": [
            "scaffold_id",
            "control",
            "expected_role",
            "machine_evaluation",
            "fixture_score",
        ],
        "audit_reference": {
            "run_artifact_uri": f"outputs/benchmark_runs/{run['run_id']}.json",
            "use_after_annotation": True,
        },
    }


def build_packet() -> dict[str, Any]:
    scenarios = _scenario_index()
    targets = []
    missing_scenarios = []
    for run in _selected_runs():
        scenario = scenarios.get(str(run.get("scenario_id")))
        if scenario is None:
            missing_scenarios.append(str(run.get("scenario_id")))
            continue
        targets.append(_annotation_target(run, scenario))

    return {
        "schema_version": "1.0",
        "packet_id": "human_calibration_fixture_packet_v1",
        "generated_at": "2026-05-23T00:00:00Z",
        "status": "annotation_packet_ready_not_human_evidence",
        "annotation_schema": str(ANNOTATION_SCHEMA_PATH.relative_to(ROOT)),
        "adjudication_schema": str(ADJUDICATION_SCHEMA_PATH.relative_to(ROOT)),
        "annotation_rubric": "docs/benchmarking/annotation_rubric.md",
        "source_run_dir": "outputs/benchmark_runs",
        "source_scenario_pack": "docs/benchmarking/scenario_pack_v0.1.json",
        "selection_method": "Deterministic stratified packet: first fixture repeat for every scenario contract.",
        "targets": targets,
        "missing_scenarios": sorted(set(missing_scenarios)),
        "protocol_requirements": {
            "minimum_independent_annotators_per_target": 3,
            "assigned_annotators_per_target": 3,
            "blind_to_scaffold": True,
            "score_scale": "normalized [0,1] per rubric dimension",
            "conflict_rule": "A dimension conflicts only when max(score) - min(score) > 0.20.",
            "adjudication_rule": "Every derived conflict requires exactly one adjudication with exactly the conflicted dimensions and the bound blinded-evidence digest.",
            "agreement_statistics": [
                "pairwise_exact_rate_by_dimension",
                "pairwise_within_0_20_rate_by_dimension",
                "pairwise_mean_absolute_delta_by_dimension",
            ],
        },
        "claim_boundary": (
            "This packet proves annotation readiness only. It is not human calibration evidence until "
            "three-or-more independent human annotations, required adjudications, verified reviewer "
            "authority, and an external attestation are preserved."
        ),
        "limitations": [
            "Targets are deterministic fixture artifacts, not live provider benchmark results.",
            "The packet intentionally withholds scaffold identity from annotator views.",
            "Assignment pseudonyms are protocol slots, not proof of independent human identity.",
            "Machine references are included for audit/adjudication after annotations are collected.",
        ],
    }


def _validate_packet(packet: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    requirements = packet.get("protocol_requirements", {})
    if packet.get("schema_version") != "1.0":
        errors.append("packet must use Protocol-v1 schema_version=1.0")
    if packet.get("status") != "annotation_packet_ready_not_human_evidence":
        errors.append("packet status must state readiness only, not completed calibration")
    if packet.get("annotation_schema") != str(ANNOTATION_SCHEMA_PATH.relative_to(ROOT)):
        errors.append("packet must use the Protocol-v1 calibration annotation-result schema")
    if packet.get("adjudication_schema") != str(ADJUDICATION_SCHEMA_PATH.relative_to(ROOT)):
        errors.append("packet must use the Protocol-v1 calibration adjudication-result schema")
    if requirements.get("minimum_independent_annotators_per_target") != 3:
        errors.append("packet must require at least three independent annotators per target")
    if requirements.get("score_scale") != "normalized [0,1] per rubric dimension":
        errors.append("packet must declare the normalized [0,1] score scale")
    if "> 0.20" not in str(requirements.get("conflict_rule", "")):
        errors.append("packet must declare the strict > 0.20 conflict threshold")
    targets = packet.get("targets", [])
    if len(targets) < 18:
        errors.append(f"expected at least 18 annotation targets, found {len(targets)}")
    if packet.get("missing_scenarios"):
        errors.append(f"packet has missing scenarios: {packet['missing_scenarios']}")

    families: dict[str, int] = defaultdict(int)
    run_ids: set[str] = set()
    for target in targets:
        run_id = str(target.get("run_id", ""))
        if run_id in run_ids:
            errors.append(f"duplicate annotation target run_id: {run_id}")
        run_ids.add(run_id)
        families[str(target.get("task_family"))] += 1
        annotator_view = target.get("annotator_view", {})
        forbidden = {"scaffold_id", "control", "expected_role", "machine_evaluation", "fixture_score"}
        leaked = sorted(forbidden & set(annotator_view))
        if leaked:
            errors.append(f"{run_id}: annotator_view leaks withheld fields: {leaked}")
        target_text = json.dumps(target).lower()
        for forbidden_value in ["full_scaffold", "plan_only", "retry_only", "schema_only"]:
            if forbidden_value in target_text:
                errors.append(f"{run_id}: packet leaks scaffold/control value {forbidden_value}")
        if "not a live provider result" not in json.dumps(annotator_view).lower():
            errors.append(f"{run_id}: annotator view must preserve live-result claim boundary")
        if target.get("blind_payload_digest") != _digest(annotator_view):
            errors.append(f"{run_id}: blind payload digest is not bound to the annotator view")
        assignments = target.get("assignments", [])
        pseudonyms = [assignment.get("annotator_pseudonym") for assignment in assignments if isinstance(assignment, dict)]
        if len(assignments) < 3 or len(pseudonyms) != len(set(pseudonyms)):
            errors.append(f"{run_id}: target must have at least three distinct assigned pseudonyms")
        if len({assignment.get("assignment_id") for assignment in assignments if isinstance(assignment, dict)}) != len(assignments):
            errors.append(f"{run_id}: target assignment identifiers must be distinct")

    expected_families = {"extraction", "risk", "research", "tool_use", "privacy", "strategy"}
    missing_families = expected_families - set(families)
    if missing_families:
        errors.append(f"packet missing task families: {sorted(missing_families)}")
    for family in expected_families:
        if families[family] < 3:
            errors.append(f"{family}: packet needs at least 3 targets")
    return errors


def _annotation_paths(annotations_dir: Path) -> list[Path]:
    return sorted(path for path in annotations_dir.glob("*.json") if path.is_file()) if annotations_dir.exists() else []


def _adjudication_paths(annotations_dir: Path) -> list[Path]:
    directory = annotations_dir / "adjudications"
    return sorted(path for path in directory.glob("*.json") if path.is_file()) if directory.exists() else []


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _schema_errors(path: Path, schema: dict[str, Any], value: Any, kind: str) -> list[str]:
    try:
        jsonschema.Draft202012Validator(schema).validate(value)
    except jsonschema.ValidationError as exc:
        return [f"{_relative(path)}: {kind} schema failed: {exc.message}"]
    return []


def _agreement_report(annotations_dir: Path, packet: dict[str, Any]) -> dict[str, Any]:
    annotation_schema = _load_json(ANNOTATION_SCHEMA_PATH)
    adjudication_schema = _load_json(ADJUDICATION_SCHEMA_PATH)
    errors: list[str] = []
    targets = {str(target["target_id"]): target for target in packet.get("targets", [])}
    expected_assignments = {
        (target_id, str(assignment["annotator_pseudonym"])): str(assignment["assignment_id"])
        for target_id, target in targets.items()
        for assignment in target.get("assignments", [])
    }
    annotations_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_assignments: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()

    annotation_paths = _annotation_paths(annotations_dir)
    for path in annotation_paths:
        try:
            annotation = _load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{_relative(path)}: annotation JSON failed: {exc}")
            continue
        schema_errors = _schema_errors(path, annotation_schema, annotation, "annotation")
        if schema_errors:
            errors.extend(schema_errors)
            continue
        target_id = str(annotation["target_id"])
        target = targets.get(target_id)
        if target is None:
            errors.append(f"{_relative(path)}: annotation target is not in the packet")
            continue
        pseudonym = str(annotation["annotator_pseudonym"])
        assignment_id = str(annotation["assignment_id"])
        pair = (target_id, pseudonym)
        if annotation["run_id"] != target["run_id"]:
            errors.append(f"{_relative(path)}: annotation run_id is not bound to its packet target")
            continue
        if "@" in pseudonym:
            errors.append(f"{_relative(path)}: annotator_pseudonym must not contain an identity address")
            continue
        if expected_assignments.get(pair) != assignment_id:
            errors.append(f"{_relative(path)}: annotation is not bound to an assigned pseudonym and assignment")
            continue
        if assignment_id in seen_assignments or pair in seen_pairs:
            errors.append(f"{_relative(path)}: duplicate annotation assignment is not independent")
            continue
        if set(annotation["dimension_scores"]) != set(ANNOTATION_DIMENSIONS):
            errors.append(f"{_relative(path)}: annotation must score exactly the protocol rubric dimensions")
            continue
        seen_assignments.add(assignment_id)
        seen_pairs.add(pair)
        annotations_by_target[target_id].append(annotation)

    dimension_rows: dict[str, dict[str, float]] = {
        dimension: {"pairs": 0, "exact": 0, "within_threshold": 0, "absolute_delta": 0}
        for dimension in ANNOTATION_DIMENSIONS
    }
    completed_targets: list[str] = []
    incomplete_targets: list[str] = []
    conflicted_dimensions: dict[str, list[str]] = {}
    for target_id, target in targets.items():
        rows = annotations_by_target.get(target_id, [])
        if not rows:
            continue
        expected = {(target_id, str(assignment["annotator_pseudonym"])) for assignment in target.get("assignments", [])}
        actual = {(target_id, str(row["annotator_pseudonym"])) for row in rows}
        if actual != expected:
            incomplete_targets.append(target_id)
            continue
        completed_targets.append(target_id)
        for left, right in combinations(rows, 2):
            for dimension in ANNOTATION_DIMENSIONS:
                delta = abs(float(left["dimension_scores"][dimension]) - float(right["dimension_scores"][dimension]))
                summary = dimension_rows[dimension]
                summary["pairs"] += 1
                summary["absolute_delta"] += delta
                if delta == 0:
                    summary["exact"] += 1
                if delta <= CONFLICT_THRESHOLD:
                    summary["within_threshold"] += 1
        disputed = [
            dimension for dimension in ANNOTATION_DIMENSIONS
            if max(float(row["dimension_scores"][dimension]) for row in rows)
            - min(float(row["dimension_scores"][dimension]) for row in rows) > CONFLICT_THRESHOLD
        ]
        if disputed:
            conflicted_dimensions[target_id] = disputed

    adjudicated_targets: set[str] = set()
    for path in _adjudication_paths(annotations_dir):
        try:
            adjudication = _load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{_relative(path)}: adjudication JSON failed: {exc}")
            continue
        schema_errors = _schema_errors(path, adjudication_schema, adjudication, "adjudication")
        if schema_errors:
            errors.extend(schema_errors)
            continue
        target_id = str(adjudication["target_id"])
        target = targets.get(target_id)
        if target is None:
            errors.append(f"{_relative(path)}: adjudication target is not in the packet")
            continue
        if target_id in adjudicated_targets:
            errors.append(f"{_relative(path)}: each conflicted target may have exactly one adjudication")
            continue
        if adjudication["run_id"] != target["run_id"]:
            errors.append(f"{_relative(path)}: adjudication run_id is not bound to its packet target")
            continue
        if "@" in str(adjudication["adjudicator_pseudonym"]):
            errors.append(f"{_relative(path)}: adjudicator_pseudonym must not contain an identity address")
            continue
        expected_dimensions = set(conflicted_dimensions.get(target_id, []))
        if not expected_dimensions:
            errors.append(f"{_relative(path)}: adjudication is not permitted for a non-conflict or incomplete target")
            continue
        if set(adjudication["final_scores"]) != expected_dimensions:
            errors.append(f"{_relative(path)}: adjudication final_scores must cover exactly the conflicted dimensions")
            continue
        if adjudication["evidence_artifact_digest"] != target["blind_payload_digest"]:
            errors.append(f"{_relative(path)}: adjudication evidence digest is not bound to the blinded packet artifact")
            continue
        adjudicated_targets.add(target_id)

    agreement = {}
    for dimension, row in dimension_rows.items():
        pairs = int(row["pairs"])
        agreement[dimension] = {
            "pair_count": pairs,
            "exact_rate": round(row["exact"] / pairs, 4) if pairs else None,
            "within_0_20_rate": round(row["within_threshold"] / pairs, 4) if pairs else None,
            "mean_absolute_delta": round(row["absolute_delta"] / pairs, 4) if pairs else None,
        }
    unresolved = sorted(set(conflicted_dimensions) - adjudicated_targets)
    return {
        "annotation_source_count": len(annotation_paths),
        "annotation_count": sum(len(rows) for rows in annotations_by_target.values()),
        "adjudication_count": len(adjudicated_targets),
        "annotated_targets_with_three_or_more_reviews": len(completed_targets),
        "completed_targets": sorted(completed_targets),
        "incomplete_targets": sorted(incomplete_targets),
        "adjudication_required_targets": sorted(conflicted_dimensions),
        "conflicted_dimensions": {target_id: conflicted_dimensions[target_id] for target_id in sorted(conflicted_dimensions)},
        "unresolved_conflict_targets": unresolved,
        "agreement_by_dimension": agreement,
        "errors": errors,
    }


def _external_ledger_errors() -> list[str]:
    ledger = _load_json(EXTERNAL_LEDGER_PATH)
    evidence_count = sum(len(ledger.get(key, [])) for key in ("independent_reproductions", "public_critiques", "human_annotation_batches"))
    if evidence_count == 0 and ledger.get("status") != "no_external_validation_completed":
        return ["external validation ledger claims completion with zero evidence records"]
    if evidence_count > 0 and ledger.get("status") != "external_validation_completed":
        return ["external validation ledger contains evidence but is not marked completed"]
    return []


def _protocol_completion_digest(packet: dict[str, Any], agreement: dict[str, Any]) -> str:
    return _digest({
        "packet_id": packet["packet_id"],
        "completed_targets": agreement["completed_targets"],
        "conflicted_dimensions": agreement["conflicted_dimensions"],
        "adjudication_required_targets": agreement["adjudication_required_targets"],
    })


def build_calibration_audit(annotations_dir: Path, packet: dict[str, Any]) -> dict[str, Any]:
    agreement = _agreement_report(annotations_dir, packet)
    validation_errors = list(agreement["errors"])
    validation_errors.extend(_external_ledger_errors())
    annotation_count = int(agreement["annotation_count"])
    target_count = len(packet.get("targets", []))
    completed = int(agreement["annotated_targets_with_three_or_more_reviews"])
    if validation_errors:
        status = "invalid_human_calibration_evidence"
    elif annotation_count == 0:
        status = "blocked_no_completed_annotations"
    elif agreement["unresolved_conflict_targets"]:
        status = "human_calibration_requires_adjudication"
    elif agreement["incomplete_targets"] or completed < target_count:
        status = "partial_human_calibration_not_release_evidence"
    else:
        status = "protocol_complete_requires_authority_attestation"
    protocol_complete = status == "protocol_complete_requires_authority_attestation"
    return {
        "schema_version": "1.0",
        "generated_at": "2026-05-23T00:00:00Z",
        "status": status,
        "annotation_dir": _relative(annotations_dir),
        "target_count": target_count,
        "annotation_source_count": agreement["annotation_source_count"],
        "annotation_count": annotation_count,
        "completed_annotation_targets": completed,
        "required_annotators_per_target": packet.get("protocol_requirements", {}).get("minimum_independent_annotators_per_target"),
        "score_scale": packet.get("protocol_requirements", {}).get("score_scale"),
        "conflict_threshold": "> 0.20",
        "agreement_by_dimension": agreement["agreement_by_dimension"],
        "adjudication_required_targets": agreement["adjudication_required_targets"],
        "conflicted_dimensions": agreement["conflicted_dimensions"],
        "unresolved_conflict_targets": agreement["unresolved_conflict_targets"],
        "incomplete_targets": agreement["incomplete_targets"],
        "protocol_completion_digest": _protocol_completion_digest(packet, agreement) if protocol_complete else None,
        "human_calibration_receipt": None,
        "receipt_state": "not_minted_authority_attestation_required",
        "validation_error_count": len(validation_errors),
        "validation_errors": validation_errors,
        "blockers_before_95": [
            "Collect at least three independent blind annotations for every assigned packet target.",
            "Resolve every derived > 0.20 per-dimension conflict with one bound adjudication covering exactly its conflicted dimensions.",
            "Verify reviewer independence and authority, preserve an immutable completion artifact, and obtain external attestation before minting a HumanCalibrationReceipt.",
            "Update outputs/external_validation.json only after concrete authority-bound annotation evidence exists.",
            "Do not treat fixture annotation readiness or a local protocol digest as live benchmark validation.",
        ],
        "claim_boundary": (
            "This audit validates protocol shape and completed annotation records when they exist. With zero "
            "annotations it is a blocker ledger, not human calibration evidence, not live benchmark evidence, "
            "and not external validation evidence. A protocol-completion digest is not a HumanCalibrationReceipt "
            "and does not establish reviewer independence, human judgment validity, or external attestation."
        ),
    }


def _validate_audit(audit: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed_statuses = {
        "blocked_no_completed_annotations",
        "invalid_human_calibration_evidence",
        "human_calibration_requires_adjudication",
        "partial_human_calibration_not_release_evidence",
        "protocol_complete_requires_authority_attestation",
    }
    if audit.get("status") not in allowed_statuses:
        errors.append("human calibration audit status is invalid")
    if audit.get("annotation_source_count", audit.get("annotation_count", 0)) == 0 and audit.get("status") != "blocked_no_completed_annotations":
        errors.append("zero annotations must keep blocked_no_completed_annotations status")
    if audit.get("validation_error_count", 0) != 0:
        errors.append("human calibration audit contains validation errors")
    if audit.get("status") in {"human_calibration_requires_adjudication", "partial_human_calibration_not_release_evidence"}:
        errors.append("incomplete or unresolved annotation records cannot pass the calibration audit")
    if audit.get("status") == "protocol_complete_requires_authority_attestation":
        if not audit.get("protocol_completion_digest"):
            errors.append("protocol-complete audit requires a completion digest")
        if audit.get("human_calibration_receipt") is not None:
            errors.append("packet audit must not mint a HumanCalibrationReceipt")
    text = json.dumps(audit).lower()
    for phrase in ["not human calibration evidence", "not live benchmark evidence", "not external validation evidence"]:
        if phrase not in text:
            errors.append(f"human calibration audit missing claim-boundary phrase: {phrase}")
    return errors


def _check_packet_file() -> list[str]:
    expected = _dump_json(build_packet())
    current = PACKET_PATH.read_text() if PACKET_PATH.exists() else ""
    return [f"{PACKET_PATH.relative_to(ROOT)} is stale"] if current != expected else []


def _check_audit_file(annotations_dir: Path, packet: dict[str, Any]) -> list[str]:
    expected = _dump_json(build_calibration_audit(annotations_dir, packet))
    current = AUDIT_PATH.read_text() if AUDIT_PATH.exists() else ""
    return [f"{AUDIT_PATH.relative_to(ROOT)} is stale"] if current != expected else []


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or check the Protocol-v1 human calibration packet.")
    parser.add_argument("--write", action="store_true", help="Write the deterministic annotation packet and audit.")
    parser.add_argument("--check", action="store_true", help="Fail if the packet or calibration state is invalid.")
    parser.add_argument("--annotations-dir", default="outputs/human_annotations")
    args = parser.parse_args()

    packet = build_packet()
    annotations_dir = ROOT / args.annotations_dir
    audit = build_calibration_audit(annotations_dir, packet)
    if args.write:
        PACKET_PATH.parent.mkdir(parents=True, exist_ok=True)
        PACKET_PATH.write_text(_dump_json(packet))
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUDIT_PATH.write_text(_dump_json(audit))
        print(f"[human-calibration] wrote {PACKET_PATH.relative_to(ROOT)} and {AUDIT_PATH.relative_to(ROOT)}")
        return 0

    errors = _validate_packet(packet)
    errors.extend(_validate_audit(audit))
    if args.check:
        errors.extend(_check_packet_file())
        errors.extend(_check_audit_file(annotations_dir, packet))
    if errors:
        for error in errors:
            print(f"[human-calibration] FAIL: {error}", file=sys.stderr)
        return 1
    print("[human-calibration] checked " f"{len(packet['targets'])} packet targets; completed annotation targets={audit['completed_annotation_targets']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
