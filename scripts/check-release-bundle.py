#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "outputs/release_bundle_audit.json"
RELEASE_MANIFEST_PATH = ROOT / "docs/release/frontier_release_manifest.json"

DISALLOWED_PATH_PARTS = {
    ".git",
    ".codex",
    ".env",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
DISALLOWED_PATH_SUFFIXES = {
    ".DS_Store",
}
DISALLOWED_PATH_PREFIXES = {
    "frontend/dist",
    "backend/.venv",
    "outputs/.cache",
}
PRIVATE_TEXT_PATTERNS = [
    re.compile("/" + r"Users/[^\s\"')<]+"),
    re.compile("/" + r"home/[^\s\"')<]+"),
    re.compile("/" + r"private/[^\s\"')<]+"),
    re.compile("/" + r"var/folders/[^\s\"')<]+"),
    re.compile("file" + r":///(?:Users|home|private|var/folders)/[^\s\"')<]+"),
]
TEXT_EXTENSIONS = {
    ".cff",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def _ensure_output_exists() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not OUTPUT_PATH.exists():
        OUTPUT_PATH.write_text("{}\n")


def _load_script(module_name: str, relative_path: str) -> Any:
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _release_artifact_paths() -> list[str]:
    _ensure_output_exists()
    module = _load_script("generate_release_manifest_for_bundle", "scripts/generate-release-manifest.py")
    return [str(item["path"]) for item in module.build_manifest()["artifacts"]]


def _required_manifest_coverage() -> dict[str, list[str]]:
    manifest = _load_script("generate_release_manifest_for_coverage", "scripts/generate-release-manifest.py")
    hf = _load_script("check_huggingface_package_for_bundle", "scripts/check-huggingface-package.py")
    frontier = _load_script("validate_frontier_package_for_bundle", "scripts/validate-frontier-package.py")
    claims = _load_script("check_claim_boundaries_for_bundle", "scripts/check-claim-boundaries.py")
    return {
        "huggingface_package_files": list(hf.PACKAGE_FILES),
        "frontier_required_files": list(frontier.REQUIRED_FILES),
        "claim_boundary_markdown": list(claims.RELEASE_MARKDOWN_TARGETS),
        "generated_release_reports": ["docs/benchmarking/sample_release_report.md"],
        "release_gate_scripts": [
            "scripts/check-doc-links.py",
            "scripts/check-public-repo-hygiene.py",
            "scripts/check-benchmark-leakage.py",
            "scripts/check-release-bundle.py",
            "scripts/generate-release-manifest.py",
            "scripts/generate-sample-report.py",
            "scripts/scan-secrets.sh",
            "scripts/trace-audit.py",
            "scripts/validate-frontier-package.py",
            "scripts/validate-protocol-artifacts.py",
            "scripts/verify-all.sh",
        ],
        "v1_surface_paths": list(manifest.v1_surface_paths()),
    }


def _is_text_file(path: Path) -> bool:
    return path.suffix in TEXT_EXTENSIONS


def _path_violation(relative_path: str) -> str | None:
    if not relative_path or relative_path.strip() != relative_path:
        return "path is empty or has leading/trailing whitespace"
    if "\\" in relative_path:
        return "path uses backslash separators"
    if relative_path.startswith("/") or re.match(r"^[A-Za-z]:", relative_path):
        return "path is absolute"
    parts = PurePosixPath(relative_path).parts
    if ".." in parts:
        return "path escapes via '..'"
    if relative_path.startswith("./"):
        return "path is not normalized"
    candidate = (ROOT / relative_path).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError:
        return "path resolves outside repo"
    if not candidate.exists():
        return "path does not exist"
    if not candidate.is_file():
        return "path is not a file"
    return None


def _disallowed_path_reason(relative_path: str) -> str | None:
    parts = set(PurePosixPath(relative_path).parts)
    blocked_parts = sorted(parts & DISALLOWED_PATH_PARTS)
    if blocked_parts:
        return f"contains disallowed path part: {blocked_parts[0]}"
    if PurePosixPath(relative_path).name in DISALLOWED_PATH_SUFFIXES:
        return "contains disallowed metadata file"
    for prefix in DISALLOWED_PATH_PREFIXES:
        if relative_path == prefix or relative_path.startswith(f"{prefix}/"):
            return f"uses disallowed release prefix: {prefix}"
    return None


def _scan_private_paths(relative_path: str) -> list[dict[str, Any]]:
    if relative_path == str(OUTPUT_PATH.relative_to(ROOT)):
        return []
    absolute = ROOT / relative_path
    if not absolute.exists() or not _is_text_file(absolute):
        return []
    try:
        text = absolute.read_text()
    except UnicodeDecodeError:
        return [
            {
                "path": relative_path,
                "line": None,
                "match": "non-utf8 text-like file",
            }
        ]
    hits: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern in PRIVATE_TEXT_PATTERNS:
            for match in pattern.finditer(line):
                hits.append(
                    {
                        "path": relative_path,
                        "line": line_number,
                        "match": match.group(0),
                    }
                )
    return hits


def build_audit() -> dict[str, Any]:
    release_paths = _release_artifact_paths()
    release_set = set(release_paths)
    root_manifest_path = str(RELEASE_MANIFEST_PATH.relative_to(ROOT))
    coverage_sources = _required_manifest_coverage()
    required_paths = sorted({path for paths in coverage_sources.values() for path in paths})
    missing_coverage = [
        path for path in required_paths if path != root_manifest_path and path not in release_set
    ]

    duplicate_paths = sorted({path for path in release_paths if release_paths.count(path) > 1})
    invalid_paths: list[dict[str, str]] = []
    missing_files: list[str] = []
    disallowed_paths: list[dict[str, str]] = []
    private_path_hits: list[dict[str, Any]] = []
    extension_counts: dict[str, int] = {}

    for relative_path in sorted(release_set | {root_manifest_path}):
        violation = _path_violation(relative_path)
        if violation:
            invalid_paths.append({"path": relative_path, "reason": violation})
            if violation == "path does not exist":
                missing_files.append(relative_path)
            continue
        disallowed = _disallowed_path_reason(relative_path)
        if disallowed:
            disallowed_paths.append({"path": relative_path, "reason": disallowed})
        suffix = (ROOT / relative_path).suffix or "[no-extension]"
        extension_counts[suffix] = extension_counts.get(suffix, 0) + 1
        private_path_hits.extend(_scan_private_paths(relative_path))

    errors_present = any(
        [
            duplicate_paths,
            invalid_paths,
            disallowed_paths,
            private_path_hits,
            missing_coverage,
            not RELEASE_MANIFEST_PATH.exists(),
        ]
    )
    status = (
        "release_bundle_audit_failed"
        if errors_present
        else "release_bundle_audit_passed_not_archive_not_clean_clone"
    )
    return {
        "schema_version": "0.1",
        "status": status,
        "release_manifest": root_manifest_path,
        "root_manifest_included_as_bundle_root": RELEASE_MANIFEST_PATH.exists(),
        "artifact_count": len(release_paths),
        "unique_artifact_count": len(release_set),
        "bundle_file_count": len(release_set | {root_manifest_path}),
        "coverage_required_count": len(required_paths),
        "missing_manifest_coverage_count": len(missing_coverage),
        "duplicate_path_count": len(duplicate_paths),
        "invalid_path_count": len(invalid_paths),
        "missing_file_count": len(missing_files),
        "disallowed_path_count": len(disallowed_paths),
        "private_path_hit_count": len(private_path_hits),
        "extension_counts": dict(sorted(extension_counts.items())),
        "coverage_sources": {key: len(paths) for key, paths in coverage_sources.items()},
        "violations": {
            "duplicate_paths": duplicate_paths,
            "invalid_paths": invalid_paths,
            "missing_files": missing_files,
            "disallowed_paths": disallowed_paths,
            "private_path_hits": private_path_hits,
            "missing_manifest_coverage": missing_coverage,
        },
        "claim_boundary": (
            "This audit validates release bundle path safety, release-manifest coverage, and "
            "private local path hygiene. It is not a published archive, not a clean clone proof, "
            "not live benchmark evidence, and not external validation or human calibration evidence."
        ),
    }


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def _validate_audit(audit: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if audit.get("status") != "release_bundle_audit_passed_not_archive_not_clean_clone":
        errors.append(f"release bundle audit status is {audit.get('status')}")
    for key in [
        "missing_manifest_coverage_count",
        "duplicate_path_count",
        "invalid_path_count",
        "missing_file_count",
        "disallowed_path_count",
        "private_path_hit_count",
    ]:
        if audit.get(key) != 0:
            errors.append(f"{key} must be 0, found {audit.get(key)}")
    if not audit.get("root_manifest_included_as_bundle_root"):
        errors.append("release manifest root file is missing")
    boundary = str(audit.get("claim_boundary", "")).lower()
    for phrase in ["not a published archive", "not a clean clone proof", "not live benchmark", "not external validation"]:
        if phrase not in boundary:
            errors.append(f"release bundle audit missing claim-boundary phrase: {phrase}")
    return errors


def _check_file() -> list[str]:
    expected = _dump_json(build_audit())
    current = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else ""
    if current != expected:
        return [f"{OUTPUT_PATH.relative_to(ROOT)} is stale"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or check release bundle hygiene audit.")
    parser.add_argument("--write", action="store_true", help="Write outputs/release_bundle_audit.json.")
    parser.add_argument("--check", action="store_true", help="Fail if the audit artifact is stale.")
    args = parser.parse_args()

    audit = build_audit()
    if args.write:
        OUTPUT_PATH.write_text(_dump_json(audit))
        print(f"[release-bundle] wrote {OUTPUT_PATH.relative_to(ROOT)}")
        return 0

    errors = _validate_audit(audit)
    if args.check:
        errors.extend(_check_file())
    if errors:
        for error in errors:
            print(f"[release-bundle] FAIL: {error}", file=sys.stderr)
        return 1
    print(
        "[release-bundle] checked "
        f"{audit['artifact_count']} release artifacts; "
        f"status={audit['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
