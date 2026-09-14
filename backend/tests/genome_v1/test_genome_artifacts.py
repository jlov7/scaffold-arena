from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from genome_v1 import GenomeDescriptor
from genome_v1.standards import load_catalog

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "backend" / "genome_v1" / "fixtures"


def test_versioned_catalog_is_source_dated_and_explicitly_catalog_only():
    catalog = load_catalog()
    assert catalog.catalog_schema == "scaffold-arena.genome-standards/1"
    assert catalog.source_date.isoformat() == "2026-08-18"
    assert catalog.claim_ceiling == "source-dated catalog metadata only"
    required_catalog_only = {
        "opencode", "qwen-code", "pi", "goose", "deepseek-harness", "kimi-cli",
        "mistral-vibe", "auggie", "github-copilot", "prime-agent", "openhands",
        "mini-swe-agent", "aider",
    }
    entries = {entry.standard_id: entry for entry in catalog.entries}
    assert required_catalog_only <= entries.keys()
    assert len(catalog.entries) >= 27
    for standard_id in required_catalog_only:
        entry = entries[standard_id]
        assert entry.support_level == "catalog_only"
        assert entry.source_urls and entry.source_date.isoformat() == "2026-08-18"
        assert entry.limitations and any("no " in limitation.lower() for limitation in entry.limitations)
    for entry in catalog.entries:
        assert entry.support_level == "catalog_only"


def test_native_fixture_validates_against_strict_model_and_generated_schema():
    payload = json.loads((FIXTURES / "native-genome-v1.json").read_text(encoding="utf-8"))
    descriptor = GenomeDescriptor.model_validate_json(json.dumps(payload))
    assert descriptor.authority.claim_ceiling == "synthetic descriptor fixture only"
    assert descriptor.with_digest().genome_digest is not None
    schema = json.loads((ROOT / "specs" / "v1" / "genome-descriptor.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)


def test_recorded_protocol_metadata_fixtures_are_synthetic_and_nonexecuting():
    for filename, protocol in (
        ("otel-recorded-metadata-v1.json", "otel"),
        ("a2a-recorded-metadata-v1.json", "a2a"),
        ("mcp-recorded-metadata-v1.json", "mcp"),
    ):
        payload = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
        assert payload["protocol"] == protocol
        assert payload["synthetic"] is True
        assert payload["recorded_metadata_only"] is True
        assert "no " in payload["claim_ceiling"].lower()
