#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

SCENARIO_PACK_PATH = ROOT / "docs/benchmarking/scenario_pack_v0.1.json"
RUN_DIR = ROOT / "outputs/benchmark_runs"
OUTPUT_PATH = ROOT / "outputs/benchmark_leakage_audit.json"

SCENARIO_PROMPT_FORBIDDEN = [
    "gold_reference",
    "gold reference",
    "answer key",
    "expected_role",
    "expected role",
    "control_type",
    "must_match_gold",
    "failure_mode",
    "mutated_fields",
    "omitted_fields",
    "total_score",
    "deterministic_weight",
    "positive control",
    "negative control",
]
TASK_PROMPT_FORBIDDEN = [
    "gold reference",
    "gold answer",
    "answer key",
    "expected output",
    "expected answer",
    "positive control",
    "negative control",
    "fixture control",
    "deterministic metric",
    "evaluation profile",
]
ARTIFACT_OUTPUT_FORBIDDEN = [
    "gold_reference",
    "gold reference",
    "answer key",
    "expected_role",
    "expected role",
    "scenario_id",
    "run_id",
    "total_score",
    "deterministic_weight",
    "fixture_control",
    "positive_control",
    "negative_control",
]
IGNORED_GOLD_TOKENS = {
    "true",
    "false",
    "positive",
    "negative",
    "backend/tasks/extraction.py",
    "backend/tasks/risk_analysis.py",
    "backend/tasks/research_synthesis.py",
    "backend/tasks/tool_use_recovery.py",
    "backend/tasks/privacy_boundary.py",
    "backend/tasks/strategy_to_system.py",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _contains(haystack: str, needle: str) -> bool:
    normalized_haystack = f" {_normalize(haystack)} "
    normalized_needle = f" {_normalize(needle)} "
    return normalized_needle in normalized_haystack


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_flatten_strings(item))
        return strings
    if isinstance(value, dict):
        strings = []
        for item in value.values():
            strings.extend(_flatten_strings(item))
        return strings
    return []


def _load_benchmark_module() -> Any:
    path = ROOT / "scripts/run-benchmark-pack.py"
    spec = importlib.util.spec_from_file_location("run_benchmark_pack_for_leakage", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path.relative_to(ROOT)}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_benchmark_pack_for_leakage"] = module
    spec.loader.exec_module(module)
    return module


def _scenario_prompt_violations(scenario: dict[str, Any]) -> list[dict[str, str]]:
    scenario_id = str(scenario.get("scenario_id", ""))
    prompt = str(scenario.get("prompt", ""))
    violations: list[dict[str, str]] = []
    for phrase in SCENARIO_PROMPT_FORBIDDEN:
        if _contains(prompt, phrase):
            violations.append({"scenario_id": scenario_id, "kind": "forbidden_metadata", "match": phrase})

    for token in _flatten_strings(scenario.get("gold_reference", {})):
        token = token.strip()
        if len(token) < 5 or token.lower() in IGNORED_GOLD_TOKENS:
            continue
        if _contains(prompt, token):
            violations.append({"scenario_id": scenario_id, "kind": "gold_reference_token", "match": token})
    return violations


def _artifact_output_violations(artifact: dict[str, Any]) -> list[dict[str, str]]:
    run_id = str(artifact.get("run_id", ""))
    output_text = json.dumps(artifact.get("output", {}), sort_keys=True)
    violations: list[dict[str, str]] = []
    for phrase in ARTIFACT_OUTPUT_FORBIDDEN:
        if _contains(output_text, phrase):
            violations.append({"run_id": run_id, "kind": "evaluation_metadata_in_output", "match": phrase})
    return violations


def _task_prompt_violations() -> list[dict[str, str]]:
    module = _load_benchmark_module()
    violations: list[dict[str, str]] = []
    for family, task in module.task_pack().items():
        prompt = str(task.get_prompt())
        for phrase in TASK_PROMPT_FORBIDDEN:
            if _contains(prompt, phrase):
                violations.append({"task_family": family, "kind": "forbidden_task_prompt_metadata", "match": phrase})
    return violations


def build_audit() -> dict[str, Any]:
    pack = _load_json(SCENARIO_PACK_PATH)
    scenarios = pack.get("scenarios", [])
    run_files = sorted(RUN_DIR.glob("*.json")) if RUN_DIR.exists() else []
    artifacts = [_load_json(path) for path in run_files]
    scenario_by_id = {
        str(scenario.get("scenario_id")): scenario
        for scenario in scenarios
        if isinstance(scenario, dict)
    }

    scenario_prompt_violations: list[dict[str, str]] = []
    for scenario in scenarios:
        if isinstance(scenario, dict):
            scenario_prompt_violations.extend(_scenario_prompt_violations(scenario))

    artifact_output_violations: list[dict[str, str]] = []
    scenario_role_mismatches: list[dict[str, str]] = []
    for artifact in artifacts:
        artifact_output_violations.extend(_artifact_output_violations(artifact))
        scenario = scenario_by_id.get(str(artifact.get("scenario_id")))
        if not scenario:
            scenario_role_mismatches.append(
                {"run_id": str(artifact.get("run_id", "")), "reason": "scenario contract missing"}
            )
            continue
        gold = scenario.get("gold_reference", {})
        control_type = gold.get("control_type") if isinstance(gold, dict) else None
        expected_role = artifact.get("expected_role")
        if control_type and expected_role != control_type:
            scenario_role_mismatches.append(
                {
                    "run_id": str(artifact.get("run_id", "")),
                    "reason": f"expected_role={expected_role} does not match scenario control_type={control_type}",
                }
            )

    task_prompt_violations = _task_prompt_violations()
    violation_count = (
        len(scenario_prompt_violations)
        + len(artifact_output_violations)
        + len(task_prompt_violations)
        + len(scenario_role_mismatches)
    )
    status = (
        "benchmark_leakage_audit_failed"
        if violation_count
        else "benchmark_leakage_audit_passed_fixture_contract_not_hidden_test"
    )
    return {
        "schema_version": "0.1",
        "generated_at": "2026-06-01T00:00:00Z",
        "status": status,
        "scenario_pack": "docs/benchmarking/scenario_pack_v0.1.json",
        "fixture_run_glob": "outputs/benchmark_runs/*.json",
        "scenario_prompt_count": len(scenarios),
        "task_prompt_count": len(_load_benchmark_module().task_pack()),
        "fixture_output_count": len(artifacts),
        "scenario_prompt_leak_count": len(scenario_prompt_violations),
        "task_prompt_leak_count": len(task_prompt_violations),
        "artifact_output_leak_count": len(artifact_output_violations),
        "scenario_role_mismatch_count": len(scenario_role_mismatches),
        "violations": {
            "scenario_prompts": scenario_prompt_violations,
            "task_prompts": task_prompt_violations,
            "fixture_outputs": artifact_output_violations,
            "scenario_role_mismatches": scenario_role_mismatches,
        },
        "claim_boundary": (
            "This audit checks obvious benchmark leakage in scenario prompts, built-in task prompts, "
            "fixture outputs, and scenario-role alignment. It is not a guarantee against all benchmark "
            "contamination, not live benchmark evidence, not human calibration evidence, and not "
            "external validation evidence."
        ),
    }


def _validate_audit(audit: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if audit.get("status") != "benchmark_leakage_audit_passed_fixture_contract_not_hidden_test":
        errors.append(f"benchmark leakage audit status is {audit.get('status')}")
    for key in [
        "scenario_prompt_leak_count",
        "task_prompt_leak_count",
        "artifact_output_leak_count",
        "scenario_role_mismatch_count",
    ]:
        if audit.get(key) != 0:
            errors.append(f"{key} must be 0, found {audit.get(key)}")
    if audit.get("scenario_prompt_count") != 18:
        errors.append(f"expected 18 scenario prompts, found {audit.get('scenario_prompt_count')}")
    if audit.get("fixture_output_count") != 54:
        errors.append(f"expected 54 fixture outputs, found {audit.get('fixture_output_count')}")
    boundary = str(audit.get("claim_boundary", "")).lower()
    for phrase in ["not a guarantee", "not live benchmark evidence", "not human calibration", "not external validation"]:
        if phrase not in boundary:
            errors.append(f"benchmark leakage audit missing claim-boundary phrase: {phrase}")
    return errors


def _check_file() -> list[str]:
    expected = _dump_json(build_audit())
    current = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else ""
    if current != expected:
        return [f"{OUTPUT_PATH.relative_to(ROOT)} is stale"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or check benchmark leakage audit.")
    parser.add_argument("--write", action="store_true", help="Write outputs/benchmark_leakage_audit.json.")
    parser.add_argument("--check", action="store_true", help="Fail if the audit artifact is stale.")
    args = parser.parse_args()

    audit = build_audit()
    if args.write:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(_dump_json(audit))
        print(f"[benchmark-leakage] wrote {OUTPUT_PATH.relative_to(ROOT)}")
        return 0

    errors = _validate_audit(audit)
    if args.check:
        errors.extend(_check_file())
    if errors:
        for error in errors:
            print(f"[benchmark-leakage] FAIL: {error}", file=sys.stderr)
        return 1
    print(
        "[benchmark-leakage] checked "
        f"{audit['scenario_prompt_count']} scenario prompts and "
        f"{audit['fixture_output_count']} fixture outputs; "
        f"status={audit['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
