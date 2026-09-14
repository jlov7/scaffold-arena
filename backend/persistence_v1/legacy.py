from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from artifacts_v1 import ArtifactStore

from .repository import ArenaRepository


@dataclass(frozen=True)
class LegacyImportResult:
    artifact_digest: str
    audit_event_id: str
    classification: str = "legacy_local_unverified"


def import_legacy_run(repository: ArenaRepository, artifact_store: ArtifactStore, project_id: str, legacy_run: Mapping[str, Any] | str | bytes) -> LegacyImportResult:
    """Quarantine a legacy run without converting absent fields into evidence."""
    if isinstance(legacy_run, Mapping):
        raw = json.dumps(legacy_run, sort_keys=True, separators=(",", ":")).encode("utf-8")
        source_format, fields = "json-object", list(legacy_run.keys())
    elif isinstance(legacy_run, str):
        raw, source_format, fields = legacy_run.encode("utf-8"), "json-text", []
    else:
        raw, source_format, fields = bytes(legacy_run), "raw-bytes", []
    digest = artifact_store.put_bytes(raw, media_type="application/json", metadata={"classification": "legacy_local_unverified", "source_format": source_format})
    repository.register_artifact(digest, size_bytes=len(raw), storage_uri=artifact_store.uri_for(digest), media_type="application/json", content_metadata={"classification": "legacy_local_unverified", "source_format": source_format})
    audit_event_id = repository.record_legacy_import(project_id, digest, source_format=source_format, observed_fields=fields)
    return LegacyImportResult(artifact_digest=digest, audit_event_id=audit_event_id)
