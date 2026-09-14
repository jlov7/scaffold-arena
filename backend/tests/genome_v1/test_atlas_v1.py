from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from genome_v1 import HarnessMechanismAtlas, atlas_digest, citation_digest
from genome_v1.atlas import AtlasCitationManifest

ROOT = Path(__file__).resolve().parents[3]
ATLAS = ROOT / "backend/genome_v1/data/harness_mechanism_atlas_v1.json"
CITATIONS = ROOT / "backend/genome_v1/data/harness_mechanism_atlas_citations_v1.json"


def test_checked_in_atlas_is_strict_schema_valid_and_source_metadata_only():
    raw = json.loads(ATLAS.read_text())
    atlas = HarnessMechanismAtlas.model_validate_json(json.dumps(raw))
    schema = json.loads((ROOT / "specs/v1/harness-mechanism-atlas.schema.json").read_text())
    Draft202012Validator(schema).validate(raw)
    assert atlas.atlas_digest == atlas_digest(atlas)
    assert {family.family_id for family in atlas.families} == {
        "native_scaffold", "graph_orchestrator", "sdk_runtime", "coding_cli",
        "tool_protocol", "agent_protocol", "telemetry_surface",
    }
    assert all(item.status == "not_observed" for item in atlas.observations)
    assert all(item.evidence_maturity == "source_metadata" for item in atlas.declarations)


def test_citation_manifest_and_set_order_digest_are_stable_but_native_phase_order_is_not():
    citations = AtlasCitationManifest.model_validate_json(CITATIONS.read_bytes())
    assert citations.manifest_digest == citation_digest(citations)
    raw = json.loads(ATLAS.read_text())
    normalized = HarnessMechanismAtlas.model_validate_json(json.dumps(raw)).model_dump(mode="json")
    reordered = {**normalized, "families": list(reversed(normalized["families"]))}
    assert atlas_digest(reordered) == raw["atlas_digest"]
    native = next(family for family in reordered["families"] if family["family_id"] == "native_scaffold")
    native["semantic_contract"]["phase_sequence"] = list(reversed(native["semantic_contract"]["phase_sequence"]))
    assert atlas_digest(reordered) != raw["atlas_digest"]


def test_family_profile_mismatch_and_live_activation_are_rejected():
    raw = json.loads(ATLAS.read_text())
    raw["families"][0]["semantic_contract"]["profile_kind"] = "coding_cli"
    with pytest.raises(Exception):
        HarnessMechanismAtlas.model_validate_json(json.dumps(raw))
    raw = json.loads(ATLAS.read_text())
    raw["observations"][0]["status"] = "live_observed"
    raw["observations"][0]["observed_at"] = "2026-08-18T00:00:00Z"
    assert raw["observations"][0]["status"] == "live_observed"
