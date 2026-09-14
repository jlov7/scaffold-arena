#!/usr/bin/env python3
"""Generate deterministic, provider-free Harness Mechanism Atlas outputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from genome_v1.atlas import (
    AtlasCitationManifest, AtlasReleaseDigest, HarnessMechanismAtlas, atlas_digest,
    citation_digest, file_digest, release_digest,
)
from genome_v1.canonical import bytes_digest

ATLAS_PATH = ROOT / "backend/genome_v1/data/harness_mechanism_atlas_v1.json"
CITATIONS_PATH = ROOT / "backend/genome_v1/data/harness_mechanism_atlas_citations_v1.json"
CATALOG_PATH = ROOT / "backend/genome_v1/data/standards_catalog_v1.json"
DOCS_PATH = ROOT / "docs/harness-mechanism-atlas-v1.md"
RELEASE_PATH = ROOT / "release/harness-mechanism-atlas-v1.digest.json"

RELEASE_FILES = (
    "backend/genome_v1/atlas.py",
    "backend/genome_v1/__init__.py",
    "backend/genome_v1/data/harness_mechanism_atlas_v1.json",
    "backend/genome_v1/data/harness_mechanism_atlas_citations_v1.json",
    "backend/genome_v1/data/standards_catalog_v1.json",
    "specs/v1/harness-mechanism-atlas.schema.json",
    "specs/v1/harness-mechanism-atlas-citation-manifest.schema.json",
    "specs/v1/harness-mechanism-atlas-release-digest.schema.json",
    "scripts/generate-harness-mechanism-atlas.py",
    "scripts/validate-harness-mechanism-atlas.py",
    "backend/tests/genome_v1/test_atlas_v1.py",
    "scripts/tests/test_harness_mechanism_atlas.py",
    "docs/harness-mechanism-atlas-v1.md",
)


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def load_models() -> tuple[HarnessMechanismAtlas, AtlasCitationManifest]:
    return (
        HarnessMechanismAtlas.model_validate_json(ATLAS_PATH.read_bytes()),
        AtlasCitationManifest.model_validate_json(CITATIONS_PATH.read_bytes()),
    )


def render_docs(atlas: HarnessMechanismAtlas, citations: AtlasCitationManifest) -> bytes:
    citation_map = {row.citation_id: row for row in citations.citations}
    observations = {row.mechanism_id: row for row in atlas.observations}
    declarations = {row.mechanism_id: row for row in atlas.declarations}
    lines = [
        "# Harness Mechanism Atlas v1",
        "",
        "This generated Atlas is a curated, provider-free evidence ledger. It does not import, execute, certify, or compare an external harness.",
        "",
        f"Source date: `{atlas.source_date}`. Atlas digest: `{atlas.atlas_digest}`.",
        "",
        "## Claim ceiling",
        "",
        atlas.claim_ceiling,
        "",
        "## Purpose and non-goals",
        "",
        "It preserves identity, family-specific semantics, declared state, observation status, evidence links, and explicit unknowns. A source pointer is not activation evidence; a fixture is metadata shape evidence only.",
        "",
        "## Family contracts",
        "",
        "| Family | Semantic namespace | Mechanisms |",
        "| --- | --- | --- |",
    ]
    for family in sorted(atlas.families, key=lambda item: item.family_id):
        lines.append(f"| `{family.family_id}` | {family.semantic_namespace} | {', '.join(f'`{item}`' for item in sorted(family.mechanism_ids))} |")
    lines.extend(["", "## Mechanism ledger", "", "| Family | Mechanism | Identity source | Declaration | Activation | Evidence maturity | Claim ceiling | Known unknowns | Citations |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"])
    for mechanism_id in sorted(declarations):
        declaration = declarations[mechanism_id]
        observation = observations[mechanism_id]
        links = ", ".join(f"[{citation_id}]({citation_map[citation_id].url})" for citation_id in sorted(declaration.citation_ids))
        source = declaration.identity.catalog_standard_id or declaration.identity.arena_name
        lines.append(
            f"| `{declaration.family_id}` | `{mechanism_id}` | `{source}` | `{declaration.declaration_status}` | `{observation.status}` | `{declaration.evidence_maturity}` | {observation.claim_ceiling} | {', '.join(f'`{item}`' for item in sorted(declaration.known_unknown_ids))} | {links} |"
        )
    lines.extend(["", "## Evidence and unknowns", "", "Every record is integrity-not-truth custody metadata. No current observation is a live runtime observation.", "", "| Evidence | Kind | Maturity | Limitations |", "| --- | --- | --- | --- |"])
    for evidence in sorted(atlas.evidence, key=lambda item: item.evidence_id):
        lines.append(f"| `{evidence.evidence_id}` | `{evidence.kind}` | `{evidence.maturity}` | {'; '.join(evidence.limitations)} |")
    lines.extend(["", "## Reproduce and verify", "", "```bash", "uv run --project backend python scripts/generate-protocol-v1-schemas.py --check", "uv run --project backend python scripts/generate-harness-mechanism-atlas.py --check", "uv run --project backend python scripts/validate-harness-mechanism-atlas.py --release-digest release/harness-mechanism-atlas-v1.digest.json", "```", "", "A release requires a real keyless signature bundle created by the tag workflow. Until then the release-signature state is `HOLD_RELEASE_SIGNATURE_REQUIRED`.", ""])
    return "\n".join(lines).encode("utf-8")


def release_bytes(atlas: HarnessMechanismAtlas, docs: bytes) -> bytes:
    entries = [{"path": path, "sha256": bytes_digest(docs) if path == "docs/harness-mechanism-atlas-v1.md" else file_digest(ROOT / path)} for path in RELEASE_FILES]
    payload: dict[str, Any] = {
        "release_digest_schema": "scaffold-arena.harness-mechanism-atlas-release-digest/1",
        "atlas_id": atlas.atlas_id,
        "source_date": atlas.source_date,
        "canonicalization": "arena-json-v1",
        "entries": entries,
        "release_digest": "sha256:" + "0" * 64,
    }
    payload["release_digest"] = release_digest(AtlasReleaseDigest.model_validate_json(json.dumps(payload)))
    return json_bytes(payload)


def expected_outputs() -> dict[Path, bytes]:
    atlas, citations = load_models()
    if atlas.atlas_digest != atlas_digest(atlas):
        raise ValueError("Atlas self-digest is stale")
    if citations.manifest_digest != citation_digest(citations):
        raise ValueError("citation manifest self-digest is stale")
    docs = render_docs(atlas, citations)
    return {DOCS_PATH: docs, RELEASE_PATH: release_bytes(atlas, docs)}


def refresh_curated_digests() -> None:
    citation_data = json.loads(CITATIONS_PATH.read_text(encoding="utf-8"))
    for citation in citation_data["citations"]:
        if citation["source_kind"] == "local_repository_source":
            citation["content_digest"] = file_digest(ROOT / citation["source_path"])
    citation_data["manifest_digest"] = "sha256:" + "0" * 64
    citations = AtlasCitationManifest.model_validate_json(json.dumps(citation_data))
    citation_data["manifest_digest"] = citation_digest(citations)
    CITATIONS_PATH.write_bytes(json_bytes(citation_data))

    atlas_data = json.loads(ATLAS_PATH.read_text(encoding="utf-8"))
    atlas_data["catalog_ref"]["sha256"] = file_digest(CATALOG_PATH)
    atlas_data["atlas_digest"] = "sha256:" + "0" * 64
    atlas = HarnessMechanismAtlas.model_validate_json(json.dumps(atlas_data))
    atlas_data["atlas_digest"] = atlas_digest(atlas)
    ATLAS_PATH.write_bytes(json_bytes(atlas_data))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="refresh curated self-digests and generated outputs")
    parser.add_argument("--check", action="store_true", help="fail when a generated output is stale")
    args = parser.parse_args(argv)
    if args.write == args.check:
        parser.error("choose exactly one of --write or --check")
    if args.write:
        refresh_curated_digests()
        outputs = expected_outputs()
        for path, contents in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
        print(f"Generated Harness Mechanism Atlas outputs ({len(outputs)} files).")
        return 0
    stale = [path.relative_to(ROOT) for path, contents in expected_outputs().items() if not path.is_file() or path.read_bytes() != contents]
    if stale:
        print("Harness Mechanism Atlas outputs are stale or missing: " + ", ".join(map(str, stale)), file=sys.stderr)
        return 1
    print("Harness Mechanism Atlas outputs are current (2 files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
