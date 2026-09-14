"""Generate the source-dated, non-certifying Genome integration matrix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from genome_v1.standards import load_catalog

JSON_OUTPUT = REPOSITORY_ROOT / "backend" / "genome_v1" / "data" / "integration_matrix_v1.json"
MARKDOWN_OUTPUT = REPOSITORY_ROOT / "docs" / "genome-integration-matrix-v1.md"
CLAIM_CEILING = "Source-dated catalog metadata and synthetic fixture shapes only; no execution, interoperability, safety, deployment, or performance claim."
FIXTURES = {
    "otel": "backend/genome_v1/fixtures/otel-recorded-metadata-v1.json",
    "a2a": "backend/genome_v1/fixtures/a2a-recorded-metadata-v1.json",
    "mcp": "backend/genome_v1/fixtures/mcp-recorded-metadata-v1.json",
}


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def generated_matrix() -> dict[str, Any]:
    catalog = load_catalog()
    selected = {row.standard_id: row for row in catalog.entries}
    rows = [{
        "integration_id": "native-genome-v1", "catalog_standard_id": None, "source_date": catalog.source_date.isoformat(),
        "support_status": "synthetic_fixture_shape_only", "fixture": "backend/genome_v1/fixtures/native-genome-v1.json",
        "claim_ceiling": "Synthetic native descriptor fixture only; no external runtime claim.",
    }]
    for integration_id, standard_id in (("otel", "otel-core"), ("a2a", "a2a"), ("mcp", "mcp")):
        row = selected[standard_id]
        rows.append({
            "integration_id": integration_id, "catalog_standard_id": row.standard_id,
            "source_date": row.source_date.isoformat(), "catalog_support_level": row.support_level,
            "support_status": "synthetic_recorded_metadata_only", "fixture": FIXTURES[integration_id],
            "claim_ceiling": CLAIM_CEILING,
        })
    return {
        "matrix_schema": "scaffold-arena.genome-integration-matrix/1",
        "generated_from": "backend/genome_v1/data/standards_catalog_v1.json",
        "source_date": catalog.source_date.isoformat(), "claim_ceiling": CLAIM_CEILING, "entries": rows,
    }


def markdown(matrix: dict[str, Any]) -> bytes:
    lines = [
        "# Genome v1 integration matrix",
        "",
        f"Source date: `{matrix['source_date']}`.",
        "",
        matrix["claim_ceiling"],
        "",
        "| Integration | Catalog support | Fixture | Claim ceiling |",
        "| --- | --- | --- | --- |",
    ]
    for row in matrix["entries"]:
        support = row.get("catalog_support_level", row["support_status"])
        lines.append(f"| `{row['integration_id']}` | `{support}` | `{row['fixture']}` | {row['claim_ceiling']} |")
    lines.extend(["", "The matrix is generated. It does not add a protocol runtime or certify any external implementation.", ""])
    return "\n".join(lines).encode("utf-8")


def expected_outputs() -> dict[Path, bytes]:
    matrix = generated_matrix()
    return {JSON_OUTPUT: _json_bytes(matrix), MARKDOWN_OUTPUT: markdown(matrix)}


def generate() -> None:
    for path, contents in expected_outputs().items():
        path.write_bytes(contents)


def check() -> list[Path]:
    return [path for path, contents in expected_outputs().items() if not path.is_file() or path.read_bytes() != contents]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated outputs are stale")
    args = parser.parse_args(argv)
    if args.check:
        stale = check()
        if stale:
            print("Genome integration matrix is stale or missing: " + ", ".join(str(path.relative_to(REPOSITORY_ROOT)) for path in stale), file=sys.stderr)
            return 1
        print("Genome integration matrix is current (2 files).")
        return 0
    generate()
    print("Generated Genome integration matrix (2 files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
