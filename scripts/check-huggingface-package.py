#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "outputs/huggingface_package_manifest.json"
HF_CARD_PATH = ROOT / "docs/huggingface/README.md"
SCENARIO_PACK_PATH = ROOT / "docs/benchmarking/scenario_pack_v0.1.json"
RUN_DIR = ROOT / "outputs/benchmark_runs"
MACHINE_LEDGER_COUNT = 10

PACKAGE_FILES = [
    "docs/huggingface/README.md",
    "docs/protocol/scaffold-arena-protocol.md",
    "docs/benchmarking/benchmark_card.md",
    "docs/benchmarking/reproducibility.md",
    "docs/benchmarking/comparison_to_existing_tools.md",
    "docs/benchmarking/scenario_pack_v0.1.json",
    "docs/benchmarking/sample_eval_card.json",
    "docs/benchmarking/sample_scaffold_card.json",
    "docs/benchmarking/failure_taxonomy.json",
    "docs/benchmarking/annotation_rubric.md",
    "outputs/benchmark_summary.json",
    "outputs/baseline_separation_report.json",
    "outputs/benchmark_leakage_audit.json",
    "outputs/external_validation_audit.json",
    "outputs/statistical_audit.json",
    "outputs/human_calibration_audit.json",
    "outputs/human_calibration_packet.json",
    "outputs/live_benchmark_preflight.json",
    "outputs/live_evidence_audit.json",
    "outputs/release_bundle_audit.json",
    "outputs/external_validation.json",
    "outputs/prior_art_positioning_audit.json",
    "specs/scenario.schema.json",
    "specs/run-artifact.schema.json",
    "specs/eval-card.schema.json",
    "specs/scaffold-card.schema.json",
    "specs/failure-taxonomy.schema.json",
    "specs/annotation.schema.json",
    "specs/external-validation.schema.json",
    "specs/v1/review-v1-calibration-annotation-result.schema.json",
    "specs/v1/review-v1-calibration-adjudication-result.schema.json",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _load_manifest_builder() -> Any:
    path = ROOT / "scripts/generate-release-manifest.py"
    spec = importlib.util.spec_from_file_location("generate_release_manifest_for_hf", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path.relative_to(ROOT)}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_release_manifest_for_hf"] = module
    spec.loader.exec_module(module)
    return module


def _release_artifact_count() -> int:
    module = _load_manifest_builder()
    return len(module.build_manifest()["artifacts"])


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def _artifact(path: str) -> dict[str, Any]:
    absolute = ROOT / path
    return {
        "path": path,
        "bytes": absolute.stat().st_size,
        "sha256": _sha256(absolute),
    }


def _reviewer_reproduction_contract() -> dict[str, Any]:
    release_artifact_count = _release_artifact_count()
    return {
        "no_key_command": "./scripts/verify-all.sh",
        "expected_gate_evidence": [
            {"label": "backend_tests", "contains": "passed"},
            {"label": "benchmark_evidence", "contains": "checked 54 benchmark run artifacts and 18 scenario contracts"},
            {"label": "prior_art", "contains": "checked 5 source-backed comparisons"},
            {"label": "benchmark_leakage", "contains": "checked 18 scenario prompts and 54 fixture outputs"},
            {"label": "human_calibration_packet", "contains": "checked 18 packet targets; completed annotation targets=0"},
            {"label": "external_validation", "contains": "checked 0 external evidence records; status=blocked_no_external_validation"},
            {"label": "live_preflight", "contains": "checked 72 planned live runs; provider=anthropic"},
            {"label": "live_evidence", "contains": "checked 0 live artifacts; status=blocked_no_live_artifacts"},
            {"label": "release_bundle", "contains": f"checked {release_artifact_count} release artifacts; status=release_bundle_audit_passed_not_archive_not_clean_clone"},
            {"label": "hf_package", "contains": "checked 54 fixture runs and 18 scenario contracts"},
            {"label": "claim_boundaries", "contains": "machine ledgers"},
            {"label": "frontend_tests", "contains": "passed"},
            {"label": "release_manifest", "contains": f"checked {release_artifact_count} release artifact hashes"},
        ],
        "key_required_followup": [
            "uv run --project backend python scripts/check-live-benchmark-readiness.py --check",
            "uv run --project backend python scripts/run-benchmark-pack.py --mode live --model-id claude-haiku-4-5 --tasks extraction,risk,research,tool_use,privacy,strategy --scaffolds bare,plan_execute_verify,tool_error_recovery,memory_critique --repeats 3",
            "./scripts/verify-all.sh",
        ],
        "required_external_evidence_after_live_runs": [
            "Commit raw outputs/live_benchmark_runs artifacts and outputs/live_benchmark_summary.json.",
            "Collect at least three independent blind Protocol-v1 annotations per sampled artifact.",
            "Publish agreement, required conflict adjudications, immutable completion, and authority-attestation artifacts before updating outputs/external_validation.json.",
            "Obtain at least one independent clean-room reproduction or serious external critique.",
        ],
        "claim_boundary": (
            "A no-key reproduction can verify package integrity, fixture separation, and release gates. "
            "It cannot validate model performance, human calibration, independent reproduction, or "
            "published archive integrity."
        ),
    }


def build_manifest() -> dict[str, Any]:
    scenario_pack = _load_json(SCENARIO_PACK_PATH)
    run_files = sorted(RUN_DIR.glob("*.json")) if RUN_DIR.exists() else []
    fixture_artifacts = [
        _artifact(str(path.relative_to(ROOT)))
        for path in run_files
    ]
    package_artifacts = [_artifact(path) for path in PACKAGE_FILES]
    return {
        "schema_version": "1.0",
        "package_name": "Scaffold Arena 0.9 fixture package",
        "status": "hf_ready_fixture_package_not_published_not_live_benchmark",
        "dataset_card": "docs/huggingface/README.md",
        "license": "mit",
        "task_families": sorted(
            {
                str(scenario["task_family"])
                for scenario in scenario_pack.get("scenarios", [])
                if isinstance(scenario, dict)
            }
        ),
        "counts": {
            "scenario_contracts": len(scenario_pack.get("scenarios", [])),
            "fixture_run_artifacts": len(fixture_artifacts),
            "package_artifacts": len(package_artifacts),
        },
        "splits": [
            {
                "name": "fixture_runs",
                "path": "outputs/benchmark_runs/*.json",
                "row_count": len(fixture_artifacts),
                "claim_boundary": "Fixture controls only; not live provider benchmark results.",
            },
            {
                "name": "scenario_contracts",
                "path": "docs/benchmarking/scenario_pack_v0.1.json",
                "row_count": len(scenario_pack.get("scenarios", [])),
                "claim_boundary": "Synthetic scenario contracts for protocol validation.",
            },
            {
                "name": "calibration_readiness",
                "path": "outputs/human_calibration_packet.json",
                "row_count": 18,
                "claim_boundary": "Protocol-v1 annotation readiness only; no completed human calibration or authority attestation.",
            },
        ],
        "required_public_claim_boundaries": [
            "No live provider benchmark results are included.",
            "Synthetic sources are not real publications.",
            "Human calibration has not been completed.",
            "External validation ledger contains zero completed evidence records.",
            "Preflight artifacts are readiness checks, not model-performance evidence.",
        ],
        "reviewer_reproduction": _reviewer_reproduction_contract(),
        "package_artifacts": package_artifacts,
        "fixture_artifacts": fixture_artifacts,
        "claim_boundary": (
            "This is a Hugging Face-ready local package manifest for fixture artifacts and protocol "
            "contracts. It is not a published Hugging Face dataset and it does not contain live "
            "provider benchmark results."
        ),
    }


def _validate_card() -> list[str]:
    text = HF_CARD_PATH.read_text()
    errors: list[str] = []
    if not text.startswith("---\n"):
        errors.append("HF card must start with YAML front matter")
    for phrase in [
        "What This Contains",
        "What This Does Not Contain",
        "Live provider benchmark results",
        "Human annotation results",
        "External-validation ledger with zero completed external evidence recorded",
        "Fixture artifacts validate protocol shape",
    ]:
        if phrase not in text:
            errors.append(f"HF card missing phrase: {phrase}")
    return errors


def _validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("status") != "hf_ready_fixture_package_not_published_not_live_benchmark":
        errors.append("HF manifest status must state fixture package, not published live benchmark")
    counts = manifest.get("counts", {})
    if counts.get("scenario_contracts") != 18:
        errors.append(f"expected 18 scenario contracts, found {counts.get('scenario_contracts')}")
    if counts.get("fixture_run_artifacts") != 54:
        errors.append(f"expected 54 fixture run artifacts, found {counts.get('fixture_run_artifacts')}")
    if "not live provider benchmark results" not in json.dumps(manifest).lower():
        errors.append("HF manifest must preserve non-live claim boundary")
    missing = [path for path in PACKAGE_FILES if not (ROOT / path).exists()]
    if missing:
        errors.append(f"missing package files: {missing}")
    if any("live_benchmark_runs" in artifact["path"] for artifact in manifest.get("fixture_artifacts", [])):
        errors.append("HF fixture package must not include live benchmark run artifacts")
    reviewer = manifest.get("reviewer_reproduction", {})
    if reviewer.get("no_key_command") != "./scripts/verify-all.sh":
        errors.append("reviewer reproduction must use ./scripts/verify-all.sh as the no-key command")
    expected_labels = {item.get("label") for item in reviewer.get("expected_gate_evidence", [])}
    for label in {
        "backend_tests",
        "benchmark_evidence",
        "prior_art",
        "benchmark_leakage",
        "human_calibration_packet",
        "external_validation",
        "live_preflight",
        "live_evidence",
        "release_bundle",
        "hf_package",
        "claim_boundaries",
        "frontend_tests",
        "release_manifest",
    }:
        if label not in expected_labels:
            errors.append(f"reviewer reproduction missing expected gate label: {label}")
    reviewer_text = json.dumps(reviewer).lower()
    release_artifact_count = _release_artifact_count()
    for fragment in [
        "checked 0 live artifacts; status=blocked_no_live_artifacts",
        "checked 0 external evidence records; status=blocked_no_external_validation",
        "checked 5 source-backed comparisons",
        "checked 18 scenario prompts and 54 fixture outputs",
        f"checked {release_artifact_count} release artifacts; status=release_bundle_audit_passed_not_archive_not_clean_clone",
        "machine ledgers",
    ]:
        if fragment not in reviewer_text:
            errors.append(f"reviewer reproduction stale expected gate fragment: {fragment}")
    for phrase in ["cannot validate model performance", "human calibration", "independent reproduction"]:
        if phrase not in reviewer_text:
            errors.append(f"reviewer reproduction missing claim-boundary phrase: {phrase}")
    return errors


def _check_file() -> list[str]:
    expected = _dump_json(build_manifest())
    current = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else ""
    if current != expected:
        return [f"{OUTPUT_PATH.relative_to(ROOT)} is stale"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or check the Hugging Face package manifest.")
    parser.add_argument("--write", action="store_true", help="Write outputs/huggingface_package_manifest.json.")
    parser.add_argument("--check", action="store_true", help="Fail if the manifest is stale.")
    args = parser.parse_args()

    manifest = build_manifest()
    if args.write:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(_dump_json(manifest))
        print(f"[hf-package] wrote {OUTPUT_PATH.relative_to(ROOT)}")
        return 0

    errors = _validate_card()
    errors.extend(_validate_manifest(manifest))
    if args.check:
        errors.extend(_check_file())

    if errors:
        for error in errors:
            print(f"[hf-package] FAIL: {error}", file=sys.stderr)
        return 1

    print(
        "[hf-package] checked "
        f"{manifest['counts']['fixture_run_artifacts']} fixture runs and "
        f"{manifest['counts']['scenario_contracts']} scenario contracts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
