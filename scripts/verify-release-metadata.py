#!/usr/bin/env python3
"""Verify Scaffold Arena version, citation, changelog, and tag truthfulness.

This script is intentionally standard-library-only so it can run before project
dependencies are installed. It validates repository declarations; it does not
claim that built artifacts are correct or that research results are valid.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

_METADATA_KEYS = {
    "schema_version",
    "version",
    "status",
    "protocol_version",
    "tag",
    "released_at",
}
_STATUSES = {"beta-unreleased", "release-candidate", "released", "withdrawn"}
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_PROTOCOL = re.compile(r"^[0-9]+\.[0-9]+$")


class ReleaseMetadataError(ValueError):
    pass


@dataclass(frozen=True)
class ReleaseMetadata:
    version: str
    status: str
    protocol_version: str
    tag: str | None
    released_at: str | None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseMetadataError(f"required file is unreadable: {path}") from exc


def _load_metadata(root: Path) -> ReleaseMetadata:
    path = root / "release" / "release-metadata.json"
    try:
        raw: Any = json.loads(_read(path))
    except json.JSONDecodeError as exc:
        raise ReleaseMetadataError("release metadata must be valid JSON") from exc
    if not isinstance(raw, dict) or set(raw) != _METADATA_KEYS:
        raise ReleaseMetadataError(
            "release metadata must contain exactly the v1 release contract keys"
        )
    if raw.get("schema_version") != "scaffold-arena-release-metadata-v1":
        raise ReleaseMetadataError("release metadata schema_version is unsupported")
    version = raw.get("version")
    status = raw.get("status")
    protocol = raw.get("protocol_version")
    tag = raw.get("tag")
    released_at = raw.get("released_at")
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        raise ReleaseMetadataError("release version must be a semantic version")
    if status not in _STATUSES:
        raise ReleaseMetadataError("release status is unsupported")
    if not isinstance(protocol, str) or _PROTOCOL.fullmatch(protocol) is None:
        raise ReleaseMetadataError("protocol_version must be major.minor")
    if tag is not None and (not isinstance(tag, str) or tag != f"v{version}"):
        raise ReleaseMetadataError("release tag must be null or v<version>")
    if released_at is not None:
        if not isinstance(released_at, str):
            raise ReleaseMetadataError("released_at must be null or an ISO date")
        try:
            date.fromisoformat(released_at)
        except ValueError as exc:
            raise ReleaseMetadataError("released_at must be an ISO date") from exc
    if status == "beta-unreleased" and (tag is not None or released_at is not None):
        raise ReleaseMetadataError(
            "an unreleased beta cannot declare a tag or release date"
        )
    if status in {"release-candidate", "released", "withdrawn"} and (
        tag is None or released_at is None
    ):
        raise ReleaseMetadataError(
            "release-candidate, released, and withdrawn states require tag and date"
        )
    return ReleaseMetadata(version, status, protocol, tag, released_at)


def _extract(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if match is None:
        raise ReleaseMetadataError(f"could not read {label}")
    return match.group(1)


def _package_versions(root: Path) -> dict[str, str]:
    with (root / "backend" / "pyproject.toml").open("rb") as handle:
        backend = tomllib.load(handle)
    try:
        backend_version = backend["project"]["version"]
    except (KeyError, TypeError) as exc:
        raise ReleaseMetadataError("backend project version is unavailable") from exc
    frontend = json.loads(_read(root / "frontend" / "package.json"))
    frontend_version = frontend.get("version") if isinstance(frontend, dict) else None
    main_version = _extract(
        r'app\s*=\s*FastAPI\([^\n]*version="([^"]+)"',
        _read(root / "backend" / "main.py"),
        "FastAPI application version",
    )
    citation_version = _extract(
        r'^version:\s*["\']?([^"\'\s]+)["\']?\s*$',
        _read(root / "CITATION.cff"),
        "citation version",
    )
    values = {
        "backend": backend_version,
        "frontend": frontend_version,
        "api": main_version,
        "citation": citation_version,
    }
    if any(not isinstance(value, str) for value in values.values()):
        raise ReleaseMetadataError("all release-bearing components require versions")
    return {key: str(value) for key, value in values.items()}


def _citation_release_date(root: Path) -> str | None:
    text = _read(root / "CITATION.cff")
    match = re.search(
        r'^date-released:\s*["\']?([^"\'\s]+)["\']?\s*$',
        text,
        flags=re.MULTILINE,
    )
    return None if match is None else match.group(1)


def _verify_repository_declarations(root: Path, metadata: ReleaseMetadata) -> None:
    versions = _package_versions(root)
    mismatched = {name: value for name, value in versions.items() if value != metadata.version}
    if mismatched:
        raise ReleaseMetadataError(
            f"version declarations disagree with release metadata: {mismatched}"
        )
    readme = _read(root / "README.md")
    if f"**{metadata.version} beta**" not in readme:
        raise ReleaseMetadataError(
            "README must display the current version and beta status explicitly"
        )
    protocol_readme = _read(root / "specs" / "v1" / "README.md")
    if f"protocol version `{metadata.protocol_version}`" not in protocol_readme:
        raise ReleaseMetadataError("protocol documentation version disagrees")

    changelog = _read(root / "CHANGELOG.md")
    citation_date = _citation_release_date(root)
    release_url = f"releases/tag/v{metadata.version}"
    compare_url = f"compare/v{metadata.version}...HEAD"
    if metadata.status == "beta-unreleased":
        if citation_date is not None:
            raise ReleaseMetadataError(
                "an unreleased beta must not contain CITATION.cff date-released"
            )
        if f"## [{metadata.version}] - UNRELEASED BETA" not in changelog:
            raise ReleaseMetadataError(
                "changelog must label the current version as an unreleased beta"
            )
        if release_url in changelog or compare_url in changelog:
            raise ReleaseMetadataError(
                "an unreleased beta must not link to nonexistent release/tag history"
            )
    else:
        if citation_date != metadata.released_at:
            raise ReleaseMetadataError(
                "citation date must equal authoritative release metadata"
            )
        if f"## [{metadata.version}] - {metadata.released_at}" not in changelog:
            raise ReleaseMetadataError(
                "released changelog heading must match authoritative metadata"
            )
        if release_url not in changelog:
            raise ReleaseMetadataError("released changelog must link to its GitHub release")


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ReleaseMetadataError(
            f"git {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _verify_tag(
    root: Path,
    metadata: ReleaseMetadata,
    tag: str | None,
    expected_sha: str | None,
) -> None:
    if tag is None:
        return
    if metadata.status not in {"release-candidate", "released"}:
        raise ReleaseMetadataError(
            "tag publication requires release-candidate or released metadata"
        )
    if tag != metadata.tag:
        raise ReleaseMetadataError("workflow tag does not match release metadata")
    if _git(root, "cat-file", "-t", tag) != "tag":
        raise ReleaseMetadataError("release tags must be annotated, not lightweight")
    target = _git(root, "rev-list", "-n", "1", tag)
    if expected_sha is not None and target != expected_sha:
        raise ReleaseMetadataError(
            "annotated release tag does not resolve to the workflow commit"
        )


def verify(
    root: Path,
    *,
    tag: str | None = None,
    expected_sha: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    metadata = _load_metadata(root)
    _verify_repository_declarations(root, metadata)
    _verify_tag(root, metadata, tag, expected_sha)
    return {
        "verdict": "PASS",
        "version": metadata.version,
        "protocol_version": metadata.protocol_version,
        "release_status": metadata.status,
        "tag": metadata.tag,
        "released_at": metadata.released_at,
        "software_provenance_not_research_truth": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify Scaffold Arena release declarations and tag binding."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--tag")
    parser.add_argument("--expected-sha")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        payload = verify(
            args.root,
            tag=args.tag,
            expected_sha=args.expected_sha,
        )
    except (OSError, ReleaseMetadataError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        print(
            json.dumps(
                {
                    "verdict": "HOLD",
                    "error": type(exc).__name__,
                    "detail": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
