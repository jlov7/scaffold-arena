#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "CITATION.cff",
    "docs/huggingface/README.md",
    "docs/paper/scaffold_arena_protocol_v0_1.md",
    "docs/benchmarking/baseline_separation.json",
    "docs/benchmarking/baseline_separation.md",
    "docs/benchmarking/comparison_to_existing_tools.md",
    "docs/benchmarking/annotation_rubric.md",
    "docs/benchmarking/sample_annotation.json",
    "specs/annotation.schema.json",
    "specs/external-validation.schema.json",
    "outputs/external_validation_audit.json",
    "outputs/external_validation.json",
    "outputs/benchmark_leakage_audit.json",
    "outputs/human_calibration_audit.json",
    "outputs/human_calibration_packet.json",
    "outputs/huggingface_package_manifest.json",
    "outputs/live_evidence_audit.json",
    "outputs/live_benchmark_preflight.json",
    "outputs/prior_art_positioning_audit.json",
    "outputs/release_bundle_audit.json",
    "outputs/statistical_audit.json",
    "docs/reviews/statistical-audit-v0.1.md",
    "docs/reviews/external-validation-ledger.md",
    "docs/release/frontier_release_manifest.json",
]

EXPECTED_TASK_FAMILIES = {
    "extraction",
    "risk",
    "research",
    "tool_use",
    "privacy",
    "strategy",
}


def _load_json(path: str) -> Any:
    return json.loads((ROOT / path).read_text())


def _check_required_files() -> list[str]:
    return [f"missing required frontier package file: {path}" for path in REQUIRED_FILES if not (ROOT / path).exists()]


def _check_citation() -> list[str]:
    text = (ROOT / "CITATION.cff").read_text()
    required = ["cff-version:", "title:", "authors:", "repository-code:", "license:"]
    return [f"CITATION.cff missing {field}" for field in required if field not in text]


def _check_hf_card() -> list[str]:
    text = (ROOT / "docs/huggingface/README.md").read_text()
    errors: list[str] = []
    if not text.startswith("---\n"):
        errors.append("docs/huggingface/README.md missing YAML front matter")
    for phrase in ["What This Does Not Contain", "Claim Boundary", "Fixture artifacts"]:
        if phrase not in text:
            errors.append(f"docs/huggingface/README.md missing phrase: {phrase}")
    return errors


def _check_annotation() -> list[str]:
    schema = _load_json("specs/annotation.schema.json")
    annotation = _load_json("docs/benchmarking/sample_annotation.json")
    try:
        jsonschema.Draft7Validator.check_schema(schema)
        jsonschema.validate(instance=annotation, schema=schema)
    except jsonschema.ValidationError as exc:
        return [f"sample annotation invalid: {exc.message}"]
    except jsonschema.SchemaError as exc:
        return [f"annotation schema invalid: {exc.message}"]
    return []


def _check_baseline_separation() -> list[str]:
    data = _load_json("docs/benchmarking/baseline_separation.json")
    errors: list[str] = []
    cases = data.get("calibration_cases", [])
    families = {case.get("task_family") for case in cases if isinstance(case, dict)}
    missing = EXPECTED_TASK_FAMILIES - families
    if missing:
        errors.append(f"baseline separation missing task families: {sorted(missing)}")
    for case in cases:
        if not isinstance(case, dict):
            errors.append("baseline separation case is not an object")
            continue
        if float(case.get("expected_separation_points", 0)) < 20:
            errors.append(f"{case.get('task_family')}: expected separation below 20 points")
        if len(case.get("negative_controls", [])) < 2:
            errors.append(f"{case.get('task_family')}: fewer than two negative controls")
        if "not" not in str(case.get("claim_boundary", "")).lower():
            errors.append(f"{case.get('task_family')}: claim boundary does not state a limitation")
    return errors


def _check_external_validation_ledger() -> list[str]:
    schema = _load_json("specs/external-validation.schema.json")
    ledger = _load_json("outputs/external_validation.json")
    try:
        jsonschema.Draft7Validator.check_schema(schema)
        jsonschema.validate(instance=ledger, schema=schema)
    except jsonschema.ValidationError as exc:
        return [f"external validation ledger invalid: {exc.message}"]
    except jsonschema.SchemaError as exc:
        return [f"external validation schema invalid: {exc.message}"]

    evidence_count = (
        len(ledger.get("independent_reproductions", []))
        + len(ledger.get("public_critiques", []))
        + len(ledger.get("human_annotation_batches", []))
    )
    if evidence_count == 0 and ledger.get("status") != "no_external_validation_completed":
        return ["external validation ledger claims completion without evidence records"]
    return []


def _check_statistical_audit() -> list[str]:
    audit = _load_json("outputs/statistical_audit.json")
    errors: list[str] = []
    if audit.get("mode") != "fixture_statistical_audit":
        errors.append("statistical audit mode must be fixture_statistical_audit")
    if not audit.get("all_families_pass"):
        errors.append("statistical audit does not pass for all families")
    families = set(audit.get("task_families", []))
    missing = EXPECTED_TASK_FAMILIES - families
    if missing:
        errors.append(f"statistical audit missing task families: {sorted(missing)}")
    limitations = " ".join(str(item).lower() for item in audit.get("limitations", []))
    if "not live provider" not in limitations and "not live provider/model" not in limitations:
        errors.append("statistical audit limitations must state that it is not live provider evidence")
    return errors


def _check_claim_boundaries() -> list[str]:
    external = _load_json("outputs/external_validation.json")
    external_audit = _load_json("outputs/external_validation_audit.json")
    leakage = _load_json("outputs/benchmark_leakage_audit.json")
    hf_manifest = _load_json("outputs/huggingface_package_manifest.json")
    calibration_audit = _load_json("outputs/human_calibration_audit.json")
    live_evidence = _load_json("outputs/live_evidence_audit.json")
    prior_art = _load_json("outputs/prior_art_positioning_audit.json")
    bundle = _load_json("outputs/release_bundle_audit.json")
    errors: list[str] = []
    if external.get("status") != "no_external_validation_completed":
        errors.append("external validation ledger must not claim completed validation")
    if external_audit.get("status") != "blocked_no_external_validation":
        errors.append("external validation audit must remain blocked without evidence records")
    if external_audit.get("evidence_count") != 0:
        errors.append("external validation audit unexpectedly claims evidence records")
    if leakage.get("status") != "benchmark_leakage_audit_passed_fixture_contract_not_hidden_test":
        errors.append("benchmark leakage audit must pass before frontier package validation")
    for key in [
        "scenario_prompt_leak_count",
        "task_prompt_leak_count",
        "artifact_output_leak_count",
        "scenario_role_mismatch_count",
    ]:
        if leakage.get(key) != 0:
            errors.append(f"benchmark leakage audit {key} must be 0")
    if hf_manifest.get("status") != "hf_ready_fixture_package_not_published_not_live_benchmark":
        errors.append("HF package manifest must not claim publication or live benchmark status")
    if calibration_audit.get("status") != "blocked_no_completed_annotations":
        errors.append("human calibration audit must remain blocked without completed annotations")
    if calibration_audit.get("annotation_count") != 0:
        errors.append("human calibration audit unexpectedly claims annotations in keyless release state")
    if live_evidence.get("status") != "blocked_no_live_artifacts":
        errors.append("live evidence audit must not claim live evidence without live artifacts")
    if live_evidence.get("live_run_count") != 0:
        errors.append("live evidence audit unexpectedly contains live artifacts")
    if prior_art.get("status") != "source_backed_prior_art_positioning_not_external_validation":
        errors.append("prior-art positioning audit must not claim external validation")
    if prior_art.get("official_source_count", 0) < 5:
        errors.append("prior-art positioning audit must cover at least five official sources")
    if bundle.get("status") != "release_bundle_audit_passed_not_archive_not_clean_clone":
        errors.append("release bundle audit must pass without claiming archive or clean-clone proof")
    for key in [
        "missing_manifest_coverage_count",
        "invalid_path_count",
        "disallowed_path_count",
        "private_path_hit_count",
    ]:
        if bundle.get(key) != 0:
            errors.append(f"release bundle audit {key} must be 0")
    return errors


def main() -> int:
    errors: list[str] = []
    errors.extend(_check_required_files())
    if not errors:
        errors.extend(_check_citation())
        errors.extend(_check_hf_card())
        errors.extend(_check_annotation())
        errors.extend(_check_baseline_separation())
        errors.extend(_check_external_validation_ledger())
        errors.extend(_check_statistical_audit())
        errors.extend(_check_claim_boundaries())

    if errors:
        for error in errors:
            print(f"[frontier-package] FAIL: {error}", file=sys.stderr)
        return 1
    print("[frontier-package] package metadata, annotation, and calibration checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
