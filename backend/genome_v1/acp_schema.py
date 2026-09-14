"""Integrity-checked access to the vendored official ACP v1 schema."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, ValidationError

_DATA = Path(__file__).with_name("data")
_BUNDLE = _DATA / "acp-v1-schema-5e89c714.json"
_DIGEST = "92c1dfcda10dd47e99127500a3763da2b471f9ac61e12b9bf0430c32cf953796"


class AcpSchemaHold(ValueError):
    pass


@lru_cache(maxsize=1)
def official_acp_v1_schema() -> dict[str, Any]:
    raw = _BUNDLE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _DIGEST:
        raise AcpSchemaHold("The vendored official ACP v1 schema does not match its custody digest.")
    schema = json.loads(raw)
    if not isinstance(schema, dict) or schema.get("title") != "Agent Client Protocol":
        raise AcpSchemaHold("The vendored ACP schema is not the expected official v1 bundle.")
    return schema


def validate_acp_fragment(name: str, payload: Mapping[str, Any]) -> None:
    schema = official_acp_v1_schema()
    fragment = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{name}"}
    try:
        Draft202012Validator(fragment).validate(dict(payload))
    except (ValidationError, KeyError) as exc:
        raise AcpSchemaHold(f"ACP {name} does not conform to the pinned official v1 schema.") from exc
