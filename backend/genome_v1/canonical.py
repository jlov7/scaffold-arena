"""Versioned, domain-separated canonicalization for Genome v1."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel

CANONICALIZATION = "arena-json-v1"
GENOME_DOMAIN = "scaffold-arena.genome"
GENOME_SCHEMA_VERSION = "1"
_SET_ARRAY_IDS = {
    "components": "component_id", "relations": "relation_id", "capabilities": "capability_id",
    "protocols": "protocol_id", "source_bindings": "source_id",
}
_SET_SCALAR_ARRAYS = frozenset({"capability_ids", "evidence_refs", "unsupported_claims", "exclusions", "agent_ids", "denied_operations", "observability_surfaces", "security_responsibilities", "compatibility_requirements"})


def _normalise(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalise(value.model_dump(mode="json"))
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        normalised: dict[str, Any] = {}
        for key, item in value.items():
            name = unicodedata.normalize("NFC", str(key))
            if name in normalised:
                raise ValueError("canonical JSON rejects post-normalization key collisions")
            normalised[name] = _normalise(item)
        return normalised
    if isinstance(value, (tuple, list)):
        return [_normalise(item) for item in value]
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    return value


def canonical_json(value: Any) -> bytes:
    """Render JSON in the fixed Arena v1 form without implicit coercion."""
    return json.dumps(
        _normalise(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def domain_envelope(payload: Any, *, domain: str = GENOME_DOMAIN, schema: str = GENOME_SCHEMA_VERSION) -> dict[str, Any]:
    return {"domain": domain, "schema": schema, "payload": _normalise(payload)}


def digest_for(payload: Any, *, domain: str = GENOME_DOMAIN, schema: str = GENOME_SCHEMA_VERSION) -> str:
    """Return the prefixed SHA-256 of a domain-separated canonical envelope."""
    return "sha256:" + hashlib.sha256(canonical_json(domain_envelope(payload, domain=domain, schema=schema))).hexdigest()


def bytes_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def descriptor_payload(descriptor: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    """Return digest material for a descriptor, excluding its self-reference."""
    raw = descriptor.model_dump(mode="json") if isinstance(descriptor, BaseModel) else dict(descriptor)
    raw.pop("genome_digest", None)
    raw.pop("canonicalization", None)
    return _sort_set_arrays(_normalise(raw))


def _sort_set_arrays(value: Any, *, field: str | None = None) -> Any:
    if isinstance(value, dict):
        return {key: _sort_set_arrays(item, field=key) for key, item in value.items()}
    if isinstance(value, list):
        values = [_sort_set_arrays(item) for item in value]
        stable_id = _SET_ARRAY_IDS.get(field or "")
        if stable_id is not None:
            if not all(isinstance(item, dict) and isinstance(item.get(stable_id), str) for item in values):
                raise ValueError(f"{field} requires stable identifiers for canonicalization")
            identities = [item[stable_id] for item in values]
            if len(identities) != len(set(identities)):
                raise ValueError(f"{field} contains duplicate stable identifiers")
            return sorted(values, key=lambda item: item[stable_id])
        if field in _SET_SCALAR_ARRAYS:
            if not all(isinstance(item, str) for item in values) or len(values) != len(set(values)):
                raise ValueError(f"{field} must be a unique set of strings")
            return sorted(values)
        return values
    return value


def genome_digest(descriptor: BaseModel | Mapping[str, Any]) -> str:
    return digest_for(descriptor_payload(descriptor))


def canonical_genome_bytes(descriptor: BaseModel | Mapping[str, Any]) -> bytes:
    """Return exact storable descriptor bytes.

    Its digest remains domain-separated through :func:`genome_digest`; unlike
    digest material, this payload remains directly parseable as a descriptor.
    """
    return canonical_json(descriptor)
