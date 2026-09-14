"""Canonical JSON and content-addressing helpers; no untrusted code is imported."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def normalise(value: Any) -> Any:
    """Convert models and tuples to JSON-native values without changing ordering."""
    if isinstance(value, BaseModel):
        return normalise(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): normalise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalise(item) for item in value]
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        normalise(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_configuration_hash(configuration: dict[str, Any]) -> str:
    """Bind an effective harness configuration to canonical JSON bytes."""
    return sha256(configuration)
