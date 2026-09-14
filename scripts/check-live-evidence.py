#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config.models import cost_usd

OUTPUT_PATH = ROOT / "outputs/live_evidence_audit.json"
LIVE_RUN_DIR = ROOT / "outputs/live_benchmark_runs"
LIVE_SUMMARY_PATH = ROOT / "outputs/live_benchmark_summary.json"
PREFLIGHT_PATH = ROOT / "outputs/live_benchmark_preflight.json"
RUN_SCHEMA_PATH = ROOT / "specs/run-artifact.schema.json"
RUN_ID_REPEAT_RE = re.compile(r"_r(\d+)$")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def _load_expected_plan() -> dict[str, Any]:
    preflight = _load_json(PREFLIGHT_PATH)
    return {
        "model_id": preflight.get("model", {}).get("model_id"),
        "task_ids": list(preflight.get("task_ids", [])),
        "scaffold_ids": list(preflight.get("scaffold_ids", [])),
        "repeat_count": int(preflight.get("repeat_count", 0)),
        "expected_run_count": int(preflight.get("expected_run_count", 0)),
        "preflight_status": preflight.get("status"),
    }


def _repeat_from_run_id(run_id: str) -> int | None:
    match = RUN_ID_REPEAT_RE.search(run_id)
    if match is None:
        return None
    return int(match.group(1))


def _validate_run_artifact(
    *,
    path: Path,
    artifact: dict[str, Any],
    schema: dict[str, Any],
    plan: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    relative = path.relative_to(ROOT)
    try:
        jsonschema.validate(instance=artifact, schema=schema)
    except jsonschema.ValidationError as exc:
        return [f"{relative}: schema invalid: {exc.message}"]

    if artifact.get("mode") != "live":
        errors.append(f"{relative}: mode must be live")
    if artifact.get("model_id") != plan["model_id"]:
        errors.append(f"{relative}: model_id does not match live preflight plan")
    if artifact.get("task_family") not in plan["task_ids"]:
        errors.append(f"{relative}: unexpected task_family {artifact.get('task_family')!r}")
    if artifact.get("scaffold_id") not in plan["scaffold_ids"]:
        errors.append(f"{relative}: unexpected scaffold_id {artifact.get('scaffold_id')!r}")
    if artifact.get("scenario_id") != f"{artifact.get('task_family')}_builtin":
        errors.append(f"{relative}: live scenario_id must use the builtin live scenario label")

    repeat = _repeat_from_run_id(str(artifact.get("run_id", "")))
    if repeat is None or repeat < 1 or repeat > plan["repeat_count"]:
        errors.append(f"{relative}: run_id must end with a repeat in the planned range")

    metrics = artifact.get("metrics", {})
    input_tokens = int(metrics.get("input_tokens", 0))
    output_tokens = int(metrics.get("output_tokens", 0))
    api_calls = int(metrics.get("num_api_calls", 0))
    if input_tokens <= 0 or output_tokens <= 0 or api_calls <= 0:
        errors.append(f"{relative}: live metrics must contain positive token usage and API calls")
    expected_cost = round(cost_usd(input_tokens, output_tokens, str(artifact.get("model_id"))), 6)
    observed_cost = round(float(metrics.get("cost_usd", -1)), 6)
    if observed_cost != expected_cost:
        errors.append(f"{relative}: cost_usd must match backend/config/models.py pricing")

    evidence_kinds = {item.get("kind") for item in artifact.get("evidence", []) if isinstance(item, dict)}
    if "live_provider_run" not in evidence_kinds:
        errors.append(f"{relative}: evidence must include live_provider_run")
    limitations = " ".join(str(item).lower() for item in artifact.get("limitations", []))
    if "aggregate claims" not in limitations:
        errors.append(f"{relative}: limitations must reject single-run aggregate claims")
    return errors


def _validate_summary(summary: dict[str, Any], plan: dict[str, Any], run_count: int) -> list[str]:
    errors: list[str] = []
    if summary.get("mode") != "live":
        errors.append("outputs/live_benchmark_summary.json: mode must be live")
    if summary.get("model_id") != plan["model_id"]:
        errors.append("outputs/live_benchmark_summary.json: model_id does not match live preflight plan")
    if int(summary.get("run_count", -1)) != run_count:
        errors.append("outputs/live_benchmark_summary.json: run_count does not match live artifacts")
    if int(summary.get("repeat_count", 0)) < plan["repeat_count"]:
        errors.append("outputs/live_benchmark_summary.json: repeat_count is below the planned repeat count")
    expected_rows = len(plan["task_ids"]) * len(plan["scaffold_ids"])
    results = summary.get("results", [])
    if len(results) != expected_rows:
        errors.append("outputs/live_benchmark_summary.json: result rows do not cover every task/scaffold pair")
    for phrase in ["external validation", "independent reproduction"]:
        if phrase not in json.dumps(summary).lower():
            errors.append(f"outputs/live_benchmark_summary.json: limitations must mention {phrase}")
    return errors


def build_audit() -> dict[str, Any]:
    plan = _load_expected_plan()
    schema = _load_json(RUN_SCHEMA_PATH)
    jsonschema.Draft7Validator.check_schema(schema)
    run_files = sorted(LIVE_RUN_DIR.glob("*.json")) if LIVE_RUN_DIR.exists() else []
    artifacts = [_load_json(path) for path in run_files]
    validation_errors: list[str] = []
    observed_cells: set[tuple[str, str, int]] = set()

    for path, artifact in zip(run_files, artifacts):
        validation_errors.extend(_validate_run_artifact(path=path, artifact=artifact, schema=schema, plan=plan))
        repeat = _repeat_from_run_id(str(artifact.get("run_id", "")))
        if repeat is not None:
            observed_cells.add((str(artifact.get("task_family")), str(artifact.get("scaffold_id")), repeat))

    expected_cells = {
        (task_id, scaffold_id, repeat)
        for task_id in plan["task_ids"]
        for scaffold_id in plan["scaffold_ids"]
        for repeat in range(1, plan["repeat_count"] + 1)
    }
    missing_cells = sorted(expected_cells - observed_cells)
    unexpected_cells = sorted(observed_cells - expected_cells)

    if run_files:
        if len(run_files) != plan["expected_run_count"]:
            validation_errors.append(
                f"expected {plan['expected_run_count']} live artifacts, found {len(run_files)}"
            )
        if missing_cells:
            validation_errors.append(f"missing planned live cells: {missing_cells[:8]}")
        if unexpected_cells:
            validation_errors.append(f"unexpected live cells: {unexpected_cells[:8]}")
        if not LIVE_SUMMARY_PATH.exists():
            validation_errors.append("outputs/live_benchmark_summary.json is required when live artifacts exist")
        else:
            validation_errors.extend(_validate_summary(_load_json(LIVE_SUMMARY_PATH), plan, len(run_files)))

    if not run_files:
        status = "blocked_no_live_artifacts"
    elif validation_errors:
        status = "invalid_live_evidence"
    else:
        status = "valid_live_artifact_set_not_human_or_external_validation"

    return {
        "schema_version": "0.1",
        "generated_at": "2026-05-23T00:00:00Z",
        "status": status,
        "ready_for_frontier_claims": False,
        "expected_run_count": plan["expected_run_count"],
        "live_run_count": len(run_files),
        "live_summary_exists": LIVE_SUMMARY_PATH.exists(),
        "model_id": plan["model_id"],
        "task_ids": plan["task_ids"],
        "scaffold_ids": plan["scaffold_ids"],
        "repeat_count": plan["repeat_count"],
        "missing_cell_count": len(missing_cells),
        "unexpected_cell_count": len(unexpected_cells),
        "validation_error_count": len(validation_errors),
        "validation_errors": validation_errors,
        "blockers_before_95": [
            "Generate the planned live provider artifacts with scripts/run-benchmark-pack.py --mode live.",
            "Commit outputs/live_benchmark_runs/*.json and outputs/live_benchmark_summary.json after validation.",
            "Calibrate deterministic metrics against independent human annotations.",
            "Record independent reproduction, public critique, or adoption in outputs/external_validation.json.",
        ],
        "claim_boundary": (
            "This audit validates the presence and shape of live benchmark artifacts when they exist. "
            "With zero live artifacts it is a blocker ledger, not live benchmark evidence. Valid live "
            "artifacts are still not human calibration or external validation evidence."
        ),
    }


def _validate_audit(audit: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if audit.get("status") not in {
        "blocked_no_live_artifacts",
        "invalid_live_evidence",
        "valid_live_artifact_set_not_human_or_external_validation",
    }:
        errors.append("live evidence audit status is invalid")
    if audit.get("live_run_count", 0) == 0 and audit.get("status") != "blocked_no_live_artifacts":
        errors.append("zero live artifacts must keep blocked_no_live_artifacts status")
    if audit.get("live_run_count", 0) > 0 and audit.get("validation_error_count", 0) > 0:
        errors.append("live artifacts are present but failed validation")
    text = json.dumps(audit).lower()
    for phrase in ["not live benchmark evidence", "not human calibration", "external validation"]:
        if phrase not in text:
            errors.append(f"live evidence audit missing claim-boundary phrase: {phrase}")
    return errors


def _check_file() -> list[str]:
    expected = _dump_json(build_audit())
    current = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else ""
    if current != expected:
        return [f"{OUTPUT_PATH.relative_to(ROOT)} is stale"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or check live benchmark evidence integrity.")
    parser.add_argument("--write", action="store_true", help="Write outputs/live_evidence_audit.json.")
    parser.add_argument("--check", action="store_true", help="Fail if the live evidence audit is stale.")
    args = parser.parse_args()

    audit = build_audit()
    if args.write:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(_dump_json(audit))
        print(f"[live-evidence] wrote {OUTPUT_PATH.relative_to(ROOT)}")
        return 0

    errors = _validate_audit(audit)
    if args.check:
        errors.extend(_check_file())
    if errors:
        for error in errors:
            print(f"[live-evidence] FAIL: {error}", file=sys.stderr)
        return 1
    print(f"[live-evidence] checked {audit['live_run_count']} live artifacts; status={audit['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
