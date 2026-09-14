"""Safe loading and content-addressing for purely declarative study packs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .canonical import sha256, sha256_bytes
from .models import ExperimentSpec, StudyPack

MANIFEST_NAME = "study-pack.json"
FORBIDDEN_SUFFIXES = {".py", ".pyc", ".pyo", ".sh", ".bash", ".zsh", ".js", ".ts", ".so", ".dylib"}


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("path escapes study pack root") from exc


def validate_study_pack_directory(directory: str | Path) -> Path:
    root = Path(directory)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("study pack root must be a real directory")
    root = root.resolve()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"study pack contains symlink: {_relative_path(root, path)}")
        if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise ValueError(f"study pack contains executable source: {_relative_path(root, path)}")
    manifest = root / MANIFEST_NAME
    if not manifest.is_file() or manifest.is_symlink():
        raise ValueError(f"study pack requires {MANIFEST_NAME}")
    return root


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {path.name}") from exc
    if not isinstance(raw, dict):
        raise TypeError(f"JSON object required: {path.name}")
    return raw


def load_study_pack(directory: str | Path) -> StudyPack:
    root = validate_study_pack_directory(directory)
    # Loading is data-only: JSON is parsed and validated; no pack file is imported or executed.
    try:
        return StudyPack.model_validate_json((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"invalid declarative study pack: {MANIFEST_NAME}") from exc


def canonical_manifest(directory: str | Path) -> dict[str, Any]:
    root = validate_study_pack_directory(directory)
    files = [path for path in root.rglob("*") if path.is_file()]
    entries = [
        {"path": _relative_path(root, path), "sha256": sha256_bytes(path.read_bytes())}
        for path in sorted(files, key=lambda item: _relative_path(root, item))
    ]
    return {"protocol_version": "1.0", "study_pack": _load_json(root / MANIFEST_NAME).get("study_pack_id"), "files": entries}


def manifest_hash(manifest: dict[str, Any]) -> str:
    return sha256(manifest)


def verify_manifest(directory: str | Path, expected_hash: str) -> bool:
    return manifest_hash(canonical_manifest(directory)) == expected_hash


def freeze_experiment(experiment: ExperimentSpec, study_pack_hash: str) -> ExperimentSpec:
    if experiment.frozen:
        raise ValueError("frozen experiments are immutable")
    if experiment.owner_approval != "approved":
        raise ValueError("frozen experiments require owner_approval='approved'")
    if len(study_pack_hash) != 64 or any(char not in "0123456789abcdef" for char in study_pack_hash):
        raise ValueError("study_pack_hash must be a SHA-256 hex digest")
    payload = experiment.model_dump(mode="json", exclude={"frozen", "freeze_hash", "frozen_at"})
    payload["study_pack_hash"] = study_pack_hash
    freeze_hash = sha256({"protocol_version": "1.0", "study_pack_hash": study_pack_hash, "experiment": payload})
    from datetime import UTC, datetime

    candidate = experiment.model_copy(
        update={
            "study_pack_hash": study_pack_hash,
            "frozen": True,
            "freeze_hash": freeze_hash,
            "frozen_at": datetime.now(UTC),
        }
    )
    # Re-enter through the canonical JSON boundary. Validated extension arrays
    # are held internally as immutable tuples, while the public contract
    # deliberately accepts JSON arrays only.
    return ExperimentSpec.model_validate_json(candidate.model_dump_json())
