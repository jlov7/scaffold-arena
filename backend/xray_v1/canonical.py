"""Canonical bytes for inert X-Ray source snapshots."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_snapshot_bytes(snapshot: Any) -> bytes:
    payload = snapshot.model_dump(mode="json", exclude={"source_digest"})
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def snapshot_digest(snapshot: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_snapshot_bytes(snapshot)).hexdigest()
