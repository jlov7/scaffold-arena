"""Static, official-source-only standards catalog for Genome v1."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field

from .models import GenomeModel, NonEmpty

CatalogSupport = Literal[
    "catalog_only", "descriptor_only", "import_only", "schema_validated", "fixture_conformance", "allowlisted_spawn",
]


class StandardCatalogEntry(GenomeModel):
    standard_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    display_name: NonEmpty
    source_urls: tuple[NonEmpty, ...] = Field(min_length=1, max_length=8)
    observed_version: NonEmpty | None = None
    source_revision: NonEmpty | None = None
    source_content_digest: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    revision_discoverability: Literal["pinned", "not_discoverable", "not_captured"] = "not_captured"
    source_date: date
    license_spdx: NonEmpty | None = None
    support_level: CatalogSupport
    limitations: tuple[NonEmpty, ...] = Field(min_length=1, max_length=16)
    migration_alias_to: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{1,127}$")

    @property
    def protocol_id(self) -> str:
        """Compatibility name for consumers filtering catalog support."""
        return self.standard_id


class StandardsCatalog(GenomeModel):
    """Versioned, source-dated catalog metadata; never runtime support proof."""

    catalog_schema: Literal["scaffold-arena.genome-standards/1"] = "scaffold-arena.genome-standards/1"
    source_date: date
    claim_ceiling: Literal["source-dated catalog metadata only"] = "source-dated catalog metadata only"
    entries: tuple[StandardCatalogEntry, ...] = Field(min_length=1, max_length=128)


def catalog_path() -> Path:
    return Path(__file__).with_name("data") / "standards_catalog_v1.json"


def load_catalog() -> StandardsCatalog:
    """Load the captured fixture; this function deliberately never uses the network."""
    payload = json.loads(catalog_path().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("standards catalog must be a versioned object")
    entries = tuple(
        StandardCatalogEntry.model_validate({
            **item, "source_date": date.fromisoformat(item["source_date"]),
            "source_urls": tuple(item["source_urls"]), "limitations": tuple(item["limitations"]),
        })
        for item in payload["entries"]
    )
    return StandardsCatalog(
        catalog_schema=payload["catalog_schema"], source_date=date.fromisoformat(payload["source_date"]),
        claim_ceiling=payload["claim_ceiling"], entries=entries,
    )


def load_standards_catalog() -> tuple[StandardCatalogEntry, ...]:
    """Load catalog entries without fetching a current external source."""
    return load_catalog().entries


def standards_by_id() -> dict[str, StandardCatalogEntry]:
    return {entry.standard_id: entry for entry in load_standards_catalog()}


def catalog_rows() -> tuple[StandardCatalogEntry, ...]:
    return load_standards_catalog()
