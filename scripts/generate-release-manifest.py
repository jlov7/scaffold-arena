#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs/release/frontier_release_manifest.json"

ARTIFACTS = [
    "AGENTS.md",
    "CITATION.cff",
    "README.md",
    "docs/protocol/scaffold-arena-protocol.md",
    "docs/benchmarking/benchmark_card.md",
    "docs/benchmarking/annotation_rubric.md",
    "docs/benchmarking/baseline_separation.json",
    "docs/benchmarking/baseline_separation.md",
    "docs/benchmarking/comparison_to_existing_tools.md",
    "docs/benchmarking/failure_taxonomy.json",
    "docs/benchmarking/failure_taxonomy.md",
    "docs/benchmarking/public_release_checklist.md",
    "docs/benchmarking/reproducibility.md",
    "docs/benchmarking/scenario_pack_v0.1.json",
    "docs/benchmarking/sample_release_report.md",
    "docs/benchmarking/sample_run_artifact.json",
    "docs/benchmarking/sample_eval_card.json",
    "docs/benchmarking/sample_scaffold_card.json",
    "docs/benchmarking/sample_scenario.json",
    "docs/benchmarking/sample_annotation.json",
    "docs/huggingface/README.md",
    "docs/paper/scaffold_arena_protocol_v0_1.md",
    "docs/reviews/benchmark-results-v0.1.md",
    "docs/reviews/external-validation-ledger.md",
    "docs/evidence-status.md",
    "docs/harness-mechanism-atlas-v1.md",
    "docs/reviews/statistical-audit-v0.1.md",
    "docs/reviews/trace-driven-frontier-audit.md",
    "specs/annotation.schema.json",
    "specs/eval-card.schema.json",
    "specs/external-validation.schema.json",
    "specs/failure-taxonomy.schema.json",
    "specs/run-artifact.schema.json",
    "specs/scaffold-card.schema.json",
    "specs/scenario.schema.json",
    "scripts/check-benchmark-evidence.py",
    "scripts/check-benchmark-leakage.py",
    "scripts/check-claim-boundaries.py",
    "scripts/check-external-validation.py",
    "scripts/check-human-calibration.py",
    "scripts/check-huggingface-package.py",
    "scripts/check-live-evidence.py",
    "scripts/check-live-benchmark-readiness.py",
    "scripts/check-prior-art-positioning.py",
    "scripts/check-doc-links.py",
    "scripts/check-release-bundle.py",
    "scripts/generate-release-manifest.py",
    "scripts/generate-harness-mechanism-atlas.py",
    "scripts/validate-harness-mechanism-atlas.py",
    "scripts/generate-sample-report.py",
    "scripts/run-benchmark-pack.py",
    "scripts/scan-secrets.sh",
    "scripts/trace-audit.py",
    "scripts/validate-frontier-package.py",
    "scripts/validate-protocol-artifacts.py",
    "scripts/validate-research-integrity.py",
    "scripts/verify-all.sh",
    "outputs/baseline_separation_report.json",
    "outputs/benchmark_leakage_audit.json",
    "outputs/benchmark_summary.json",
    "outputs/external_validation_audit.json",
    "outputs/external_validation.json",
    "outputs/human_calibration_audit.json",
    "outputs/human_calibration_packet.json",
    "outputs/huggingface_package_manifest.json",
    "outputs/live_evidence_audit.json",
    "outputs/live_benchmark_preflight.json",
    "outputs/prior_art_positioning_audit.json",
    "outputs/release_bundle_audit.json",
    "outputs/statistical_audit.json",
    "release/harness-mechanism-atlas-v1.digest.json",
]

# The v1 workbench is deliberately enumerated by source roots rather than by
# a hand-maintained sample list.  This keeps a new protocol, test, study-pack,
# deployment, or release-doc file from silently falling outside the manifest.
V1_SURFACE_ROOTS = (
    ".github",
    "examples",
    "backend/adapters_v1",
    "backend/analysis_v1",
    "backend/api",
    "backend/api/v1",
    "backend/artifacts_v1",
    "backend/auth_v1",
    "backend/arena_cli",
    "backend/evaluation_v1",
    "backend/execution_v1",
    "backend/evidence_v1",
    "backend/factors_v1",
    "backend/genome_v1",
    "backend/observatory_v1",
    "backend/migrations",
    "backend/persistence_v1",
    "backend/protocol_v1",
    "backend/review_v1",
    "backend/services_v1",
    "backend/xray_v1",
    "backend/audit",
    "backend/autopsy",
    "backend/config",
    "backend/core",
    "backend/evaluation",
    "backend/report",
    "backend/scaffolds",
    "backend/tasks",
    "backend/utils",
    "backend/tests",
    "frontend/src",
    "frontend/scripts",
    "frontend/tests",
    "study_packs",
    "deploy",
    "docs",
    "scripts",
    "specs",
)
V1_SURFACE_FILES = (
    ".dockerignore",
    ".env.example",
    ".gitignore",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "Dockerfile",
    "LICENSE",
    "SECURITY.md",
    "SUPPORT.md",
    "backend/.dockerignore",
    "backend/.env.example",
    "backend/Dockerfile",
    "backend/README.md",
    "backend/main.py",
    "backend/pyproject.toml",
    "backend/uv.lock",
    "backend/core/run_lifecycle.py",
    "backend/alembic.ini",
    "compose.postgres-test.yml",
    "docker-compose.yml",
    "frontend/.dockerignore",
    "frontend/Dockerfile",
    "frontend/README.md",
    "frontend/eslint.config.js",
    "frontend/index.html",
    "frontend/nginx.conf",
    "frontend/package.json",
    "frontend/playwright.config.ts",
    "frontend/pnpm-lock.yaml",
    "frontend/pnpm-workspace.yaml",
    "frontend/tsconfig.app.json",
    "frontend/tsconfig.json",
    "frontend/tsconfig.node.json",
    "frontend/vercel.json",
    "frontend/vite.config.ts",
    "outputs/scale_validation.json",
    "railway.toml",
    "scripts/generate-protocol-v1-schemas.py",
    "scripts/test-postgres-v1.sh",
    "scripts/verify-clean-clone.sh",
)


def v1_surface_paths() -> list[str]:
    paths = set(V1_SURFACE_FILES)
    for relative_root in V1_SURFACE_ROOTS:
        root = ROOT / relative_root
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path == MANIFEST_PATH:
                continue
            paths.add(str(path.relative_to(ROOT)))
    return sorted(paths)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def build_manifest() -> dict:
    artifacts = ARTIFACTS + v1_surface_paths() + [
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "outputs/benchmark_runs").glob("*.json"))
    ]
    artifacts.extend(
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "outputs/live_benchmark_runs").glob("*.json"))
    )
    if (ROOT / "outputs/live_benchmark_summary.json").exists():
        artifacts.append("outputs/live_benchmark_summary.json")
    artifacts = list(dict.fromkeys(artifacts))
    return {
        "schema_version": "0.1",
        "release_name": "Scaffold Arena 0.9.1 candidate",
        "claim_boundary": "This manifest covers the local Scaffold Arena 0.9.1 candidate workbench, protocol/package artifacts, tests, and fixture evidence; it is not live deployment, live provider benchmark, human calibration, external reproduction, or release assurance evidence.",
        "artifacts": [
            {"path": path, "sha256": _sha256(ROOT / path)}
            for path in artifacts
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or check the frontier release provenance manifest.")
    parser.add_argument("--check", action="store_true", help="Fail if the checked-in manifest is stale.")
    args = parser.parse_args()

    manifest = build_manifest()
    serialized = json.dumps(manifest, indent=2, sort_keys=False) + "\n"
    if args.check:
        current = MANIFEST_PATH.read_text() if MANIFEST_PATH.exists() else ""
        if current != serialized:
            print("[manifest] FAIL: docs/release/frontier_release_manifest.json is stale", file=sys.stderr)
            return 1
        print(f"[manifest] checked {len(manifest['artifacts'])} release artifact hashes")
        return 0

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(serialized)
    print(f"[manifest] wrote {MANIFEST_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
