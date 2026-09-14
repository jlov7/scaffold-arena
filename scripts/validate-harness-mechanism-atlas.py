#!/usr/bin/env python3
"""Fail-closed semantic validation for the provider-free Atlas v1."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from genome_v1.atlas import (
    AtlasCitationManifest,
    AtlasReleaseDigest,
    HarnessMechanismAtlas,
    atlas_digest,
    citation_digest,
    file_digest,
    release_digest,
)
from genome_v1.standards import load_catalog

DEFAULT_ATLAS = ROOT / "backend/genome_v1/data/harness_mechanism_atlas_v1.json"
DEFAULT_CITATIONS = ROOT / "backend/genome_v1/data/harness_mechanism_atlas_citations_v1.json"
DEFAULT_SCHEMA = ROOT / "specs/v1/harness-mechanism-atlas.schema.json"
DEFAULT_CITATION_SCHEMA = ROOT / "specs/v1/harness-mechanism-atlas-citation-manifest.schema.json"
DEFAULT_RELEASE_SCHEMA = ROOT / "specs/v1/harness-mechanism-atlas-release-digest.schema.json"
DEFAULT_RELEASE = ROOT / "release/harness-mechanism-atlas-v1.digest.json"
RELEASE_METADATA = ROOT / "release/release-metadata.json"
OIDC_ISSUER = "https://token.actions.githubusercontent.com"


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return payload


def _validate_schema(payload: dict[str, Any], schema_path: Path) -> None:
    schema = _load(schema_path)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)


def _safe_repo_path(path: str, *, approved_roots: tuple[str, ...]) -> Path:
    if path.startswith("/") or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/")):
        raise ValueError("artifact path is not a safe relative path")
    if not path.startswith(approved_roots):
        raise ValueError("artifact path is outside an approved Atlas root")
    resolved = (ROOT / path).resolve(strict=True)
    if ROOT not in resolved.parents:
        raise ValueError("artifact path resolves outside the repository")
    current = ROOT / path
    if current.is_symlink():
        raise ValueError("artifact path cannot be a symlink")
    return resolved


def _require_refs(values: tuple[str, ...], known: set[str], label: str) -> None:
    missing = sorted(set(values) - known)
    if missing:
        raise ValueError(f"{label} has unresolved IDs: {', '.join(missing)}")


def _validate_semantics(atlas: HarnessMechanismAtlas, citations: AtlasCitationManifest, catalog_path: Path, release: AtlasReleaseDigest) -> None:
    if atlas.atlas_digest != atlas_digest(atlas):
        raise ValueError("atlas_digest does not bind the Atlas payload")
    if citations.manifest_digest != citation_digest(citations):
        raise ValueError("manifest_digest does not bind the citation manifest")
    if atlas.catalog_ref.sha256 != file_digest(catalog_path):
        raise ValueError("catalog_ref sha256 does not match catalog bytes")
    if atlas.catalog_ref.source_date != atlas.source_date or citations.source_date != atlas.source_date:
        raise ValueError("Atlas and citation source dates must agree")

    catalog = {row.standard_id: row for row in load_catalog().entries}
    citation_map = {row.citation_id: row for row in citations.citations}
    family_map = {row.family_id: row for row in atlas.families}
    declaration_map = {row.mechanism_id: row for row in atlas.declarations}
    evidence_map = {row.evidence_id: row for row in atlas.evidence}
    unknown_ids = {row.unknown_id for row in atlas.known_unknowns}
    if set(family_map) != {"native_scaffold", "graph_orchestrator", "sdk_runtime", "coding_cli", "tool_protocol", "agent_protocol", "telemetry_surface"}:
        raise ValueError("Atlas must contain each required semantic family exactly once")

    for citation in citations.citations:
        _require_refs(citation.supported_mechanism_ids, set(declaration_map), "citation mechanisms")
        if citation.source_kind == "local_repository_source":
            path = _safe_repo_path(citation.source_path or "", approved_roots=("backend/genome_v1/",))
            if citation.content_digest != file_digest(path):
                raise ValueError("local citation content digest is stale")
            expected_url = f"https://github.com/jlov7/scaffold-arena/blob/{citation.source_revision}/{citation.source_path}"
            if citation.url != expected_url:
                raise ValueError("local citation URL must be pinned to its source revision and path")

    for family in atlas.families:
        _require_refs(family.mechanism_ids, set(declaration_map), "family mechanisms")
        _require_refs(family.citation_ids, set(citation_map), "family citations")
        _require_refs(family.known_unknown_ids, unknown_ids, "family unknowns")
        if family.semantic_contract.profile_kind != family.family_id:
            raise ValueError("family semantic profile is not discriminated by its family")

    by_family: dict[str, set[str]] = {key: set() for key in family_map}
    for declaration in atlas.declarations:
        by_family[declaration.family_id].add(declaration.mechanism_id)
        _require_refs(declaration.citation_ids, set(citation_map), "declaration citations")
        _require_refs(declaration.identity.citation_ids, set(citation_map), "identity citations")
        _require_refs(declaration.evidence_ids, set(evidence_map), "declaration evidence")
        _require_refs(declaration.known_unknown_ids, unknown_ids, "declaration unknowns")
        if declaration.identity.identity_kind == "external_catalog":
            row = catalog.get(declaration.identity.catalog_standard_id or "")
            if row is None:
                raise ValueError("external declaration lacks a catalog entry")
            if declaration.evidence_maturity != "source_metadata" or row.support_level != "catalog_only":
                raise ValueError("external catalog rows cannot exceed source metadata")
            if declaration.identity.version != row.observed_version or declaration.identity.license_spdx != row.license_spdx:
                raise ValueError("external declaration identity contradicts catalog metadata")
            if declaration.identity.source_revision_state != row.revision_discoverability:
                raise ValueError("external declaration revision state contradicts catalog")
            for citation_id in declaration.citation_ids:
                citation = citation_map[citation_id]
                if citation.url not in row.source_urls:
                    raise ValueError("external citation URL is not an exact captured catalog URL")
                if citation.source_revision != row.source_revision or citation.content_digest != row.source_content_digest:
                    raise ValueError("external citation revision or digest contradicts catalog")
                if citation.license_spdx != row.license_spdx or citation.revision_discoverability != row.revision_discoverability:
                    raise ValueError("external citation license or revision state contradicts catalog")
        elif declaration.evidence_maturity not in {"source_metadata", "descriptor", "synthetic_fixture"}:
            raise ValueError("native declarations cannot claim an observation in v1")
    for family_id, mechanism_ids in by_family.items():
        if mechanism_ids != set(family_map[family_id].mechanism_ids):
            raise ValueError("family mechanism list does not exactly match declarations")

    seen_observations: set[str] = set()
    for observation in atlas.observations:
        if observation.mechanism_id in seen_observations:
            raise ValueError("each mechanism must have exactly one observation")
        seen_observations.add(observation.mechanism_id)
        _require_refs(observation.evidence_ids, set(evidence_map), "observation evidence")
        _require_refs(observation.known_unknown_ids, unknown_ids, "observation unknowns")
        if observation.status not in {"not_observed", "synthetic_metadata_fixture"}:
            raise ValueError("Atlas v1 cannot claim observed or reproduced activation")
        if observation.status == "synthetic_metadata_fixture":
            path = _safe_repo_path(observation.artifact_path or "", approved_roots=("backend/genome_v1/fixtures/",))
            if observation.artifact_digest != file_digest(path) or "synthetic" not in observation.claim_ceiling.lower():
                raise ValueError("synthetic observation must bind fixture bytes and claim ceiling")
    if seen_observations != set(declaration_map):
        raise ValueError("each declaration requires exactly one observation")

    for evidence in atlas.evidence:
        _require_refs(evidence.citation_ids, set(citation_map), "evidence citations")
        _require_refs(evidence.known_unknown_ids, unknown_ids, "evidence unknowns")
        if evidence.maturity in {"local_observation", "live_observation", "independent_reproduction"}:
            raise ValueError("Atlas v1 evidence maturity cannot claim an observation")
        if evidence.artifact_path:
            path = _safe_repo_path(evidence.artifact_path, approved_roots=("backend/genome_v1/",))
            if evidence.artifact_digest != file_digest(path):
                raise ValueError("evidence artifact digest is stale")

    if release.release_digest != release_digest(release):
        raise ValueError("release digest self-binding is stale")
    allowed = {
        "backend/genome_v1/atlas.py", "backend/genome_v1/__init__.py", "backend/genome_v1/data/harness_mechanism_atlas_v1.json",
        "backend/genome_v1/data/harness_mechanism_atlas_citations_v1.json", "backend/genome_v1/data/standards_catalog_v1.json",
        "specs/v1/harness-mechanism-atlas.schema.json", "specs/v1/harness-mechanism-atlas-citation-manifest.schema.json",
        "specs/v1/harness-mechanism-atlas-release-digest.schema.json", "scripts/generate-harness-mechanism-atlas.py",
        "scripts/validate-harness-mechanism-atlas.py", "backend/tests/genome_v1/test_atlas_v1.py", "scripts/tests/test_harness_mechanism_atlas.py", "docs/harness-mechanism-atlas-v1.md",
    }
    for entry in release.entries:
        if entry.path not in allowed or entry.sha256 != file_digest(_safe_repo_path(entry.path, approved_roots=("backend/", "specs/", "scripts/", "docs/"))):
            raise ValueError("release digest entry is unallowlisted or stale")


def _verify_signature(bundle: Path, payload: Path) -> tuple[str, str | None]:
    if not bundle.is_file():
        return "HOLD_RELEASE_SIGNATURE_REQUIRED", "signature bundle is missing"
    cosign = shutil.which("cosign")
    if cosign is None:
        return "HOLD_RELEASE_SIGNATURE_VERIFIER_UNAVAILABLE", "cosign is not installed"
    version = str(_load(RELEASE_METADATA).get("version", ""))
    if not re.fullmatch(r"[0-9]+[.][0-9]+[.][0-9]+", version):
        return "FAIL", "release version is invalid"
    identity = (
        r"^https://github[.]com/jlov7/scaffold-arena/[.]github/workflows/"
        rf"release[.]yml@refs/tags/v{re.escape(version)}$"
    )
    try:
        verified = subprocess.run(
            [
                cosign,
                "verify-blob",
                "--bundle",
                str(bundle),
                "--certificate-oidc-issuer",
                OIDC_ISSUER,
                "--certificate-identity-regexp",
                identity,
                str(payload),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "FAIL", "signature verification could not complete"
    if verified.returncode != 0:
        return "FAIL", "signature bundle is invalid or does not bind the release workflow and payload"
    return "PASS", None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas", type=Path, default=DEFAULT_ATLAS)
    parser.add_argument("--citations", type=Path, default=DEFAULT_CITATIONS)
    parser.add_argument("--catalog", type=Path, default=ROOT / "backend/genome_v1/data/standards_catalog_v1.json")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--citation-schema", type=Path, default=DEFAULT_CITATION_SCHEMA)
    parser.add_argument("--release-schema", type=Path, default=DEFAULT_RELEASE_SCHEMA)
    parser.add_argument("--release-digest", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--require-signature", type=Path)
    args = parser.parse_args(argv)
    try:
        atlas_raw, citations_raw, release_raw = _load(args.atlas), _load(args.citations), _load(args.release_digest)
        _validate_schema(atlas_raw, args.schema)
        _validate_schema(citations_raw, args.citation_schema)
        _validate_schema(release_raw, args.release_schema)
        atlas = HarnessMechanismAtlas.model_validate_json(json.dumps(atlas_raw))
        citations = AtlasCitationManifest.model_validate_json(json.dumps(citations_raw))
        release = AtlasReleaseDigest.model_validate_json(json.dumps(release_raw))
        _validate_semantics(atlas, citations, args.catalog, release)
    except Exception as error:
        print(json.dumps({"verdict": "FAIL", "error": str(error)}, sort_keys=True))
        return 1
    result = {"verdict": "PASS", "atlas_digest": atlas.atlas_digest, "source_date": atlas.source_date, "counts": {"families": len(atlas.families), "mechanisms": len(atlas.declarations), "citations": len(citations.citations)}, "claim_ceiling": atlas.claim_ceiling}
    if args.require_signature:
        verdict, detail = _verify_signature(args.require_signature, args.release_digest)
        result.update({"verdict": verdict, "signature_bundle": str(args.require_signature)})
        if detail:
            result["signature_detail"] = detail
        print(json.dumps(result, sort_keys=True))
        if verdict.startswith("HOLD_"):
            return 2
        return 0 if verdict == "PASS" else 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
