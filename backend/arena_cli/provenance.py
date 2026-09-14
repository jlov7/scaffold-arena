"""Automatic, secret-safe local provenance capture for StudyPack executions."""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from protocol_v1 import ExecutionProvenance, StudyPack
from protocol_v1.canonical import sha256, sha256_bytes
from protocol_v1.models import ProtocolModel, ProvenanceSourceRef
from pydantic import ConfigDict, Field

_CAPTURE_METHOD = "automatic-local-v1"
_MAX_CAPTURE_FILE_BYTES = 16 * 1024 * 1024
_MAX_CAPTURE_FILES = 10_000
_MAX_CAPTURE_TOTAL_BYTES = 256 * 1024 * 1024
_LOCKFILE_NAMES = frozenset(
    {
        "uv.lock",
        "pyproject.toml",
        "requirements.txt",
        "requirements.lock",
        "poetry.lock",
        "pdm.lock",
        "Pipfile.lock",
        "pnpm-lock.yaml",
        "package-lock.json",
        "yarn.lock",
        "package.json",
        "Cargo.lock",
        "go.sum",
    }
)
_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "__pycache__",
    }
)
_SENSITIVE_PARTS = frozenset(
    {
        ".aws",
        ".gnupg",
        ".secrets",
        ".ssh",
        "secrets",
    }
)
_SENSITIVE_NAMES = frozenset(
    {
        ".env",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "credentials",
        "credentials.json",
        "id_ed25519",
        "id_rsa",
        "secrets.json",
    }
)
_SENSITIVE_SUFFIXES = frozenset(
    {
        ".jks",
        ".key",
        ".keystore",
        ".p12",
        ".pem",
        ".pfx",
    }
)


class AutomaticProvenanceCapture(ProtocolModel):
    """Observed local provenance plus limitations that prevent overclaiming."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    capture_method: Literal["automatic-local-v1"] = _CAPTURE_METHOD
    repository_dirty: bool
    provenance: ExecutionProvenance
    limitations: tuple[str, ...] = Field(min_length=1)


def collect_study_pack_provenance(
    *,
    repository_root: str | Path,
    study_pack_path: str | Path,
    captured_at: datetime | None = None,
    capture_material: dict[str, Any] | None = None,
) -> AutomaticProvenanceCapture:
    """Capture reproducible local identities without reading environment values.

    The function observes Git state, dependency lockfiles, installed package
    versions, runtime identity, and the strict StudyPack declaration. It hashes
    those observations but never serializes the repository path, environment
    variables, credentials, command output beyond Git metadata, or file bytes.
    Secret-like paths and symlinks are excluded from source manifests; strict
    file, count, and total-byte ceilings prevent capture from becoming a data
    exfiltration or resource-exhaustion primitive.
    """

    root = Path(repository_root).expanduser().resolve()
    pack_path = Path(study_pack_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("repository_root must be an existing directory")
    if not pack_path.is_file():
        raise ValueError("study_pack_path must be a readable StudyPack JSON file")

    pack = StudyPack.model_validate_json(pack_path.read_bytes())
    captured = captured_at or datetime.now(UTC)
    if captured.tzinfo is None or captured.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    captured = captured.astimezone(UTC)

    git = _capture_git(root)
    runtime_identity = _runtime_identity()
    environment_identity = _environment_identity(root)
    source_refs = _source_refs(pack, pack_path)

    def observed_hash(name: str, value: Any) -> str:
        if capture_material is not None:
            capture_material[name] = value
        return sha256(value)

    if capture_material is not None:
        capture_material["code_hash"] = git["material"]
        capture_material["git_observations"] = git.get("observations")

    provenance = ExecutionProvenance(
        code_revision=git["revision"],
        code_hash=git["code_hash"],
        runtime_image=runtime_identity["label"],
        runtime_image_hash=observed_hash("runtime_image_hash", runtime_identity),
        environment_hash=observed_hash("environment_hash", environment_identity),
        prompt_hash=observed_hash("prompt_hash",
            [
                {
                    "scenario_id": scenario.scenario_id,
                    "prompt": scenario.prompt,
                    "output_contract": (
                        scenario.output_contract.model_dump(mode="json")
                        if scenario.output_contract
                        else None
                    ),
                }
                for scenario in sorted(pack.scenarios, key=lambda item: item.scenario_id)
            ]
        ),
        context_hash=observed_hash("context_hash",
            [
                {
                    "scenario_id": scenario.scenario_id,
                    "extensions": dict(scenario.extensions),
                    "source_label": scenario.source_label,
                    "data_classification": scenario.data_classification,
                    "control_role": scenario.control_role,
                    "cluster_id": scenario.cluster_id,
                    "variant": scenario.variant,
                    "pair_id": scenario.pair_id,
                    "initial_state": (
                        scenario.initial_state.model_dump(mode="json")
                        if scenario.initial_state
                        else None
                    ),
                    "reference_solution": (
                        scenario.reference_solution.model_dump(mode="json")
                        if scenario.reference_solution
                        else None
                    ),
                    "evidence_sources": [
                        source.model_dump(mode="json")
                        for source in scenario.evidence_sources
                    ],
                    "faults": [
                        fault.model_dump(mode="json")
                        for fault in scenario.fault_definitions
                    ],
                    "fault_schedule": [
                        entry.model_dump(mode="json")
                        for entry in scenario.fault_schedule
                    ],
                    "allowed_claims": list(scenario.allowed_claims),
                    "limitations": list(scenario.limitations),
                }
                for scenario in sorted(pack.scenarios, key=lambda item: item.scenario_id)
            ]
        ),
        tool_hash=observed_hash("tool_hash",
            {
                "scenario_tools": [
                    {
                        "scenario_id": scenario.scenario_id,
                        "fixtures": [
                            fixture.model_dump(mode="json")
                            for fixture in scenario.tool_fixtures
                        ],
                    }
                    for scenario in sorted(
                        pack.scenarios, key=lambda item: item.scenario_id
                    )
                ],
                "harness_tools": [
                    {
                        "harness_id": harness.harness_id,
                        "allowed_tools": list(harness.allowed_tools),
                        "capabilities": harness.capabilities.model_dump(mode="json"),
                        "schema_hashes": harness.schema_hashes.model_dump(mode="json"),
                    }
                    for harness in sorted(
                        pack.harnesses, key=lambda item: item.harness_id
                    )
                ],
            }
        ),
        source_refs=source_refs,
        captured_at=captured,
    )

    limitations = [
        "local automatic capture is custody metadata, not a signed build attestation",
        "runtime identity describes the current Python process, not an isolated container",
        "installed package metadata does not prove the target deployment environment",
        "secret-like paths and symlinks are excluded from content manifests; Git dirty state still records their presence without hashing their contents",
        (
            "source capture is bounded to "
            f"{_MAX_CAPTURE_FILES} files, {_MAX_CAPTURE_FILE_BYTES} bytes per file, "
            f"and {_MAX_CAPTURE_TOTAL_BYTES} bytes in total"
        ),
    ]
    if git["dirty"]:
        limitations.append(
            "repository had tracked or untracked changes; code_hash binds the observable non-secret dirty state"
        )
    if git["revision"] == "unversioned-source":
        limitations.append(
            "Git identity was unavailable; code_hash binds a bounded source manifest instead"
        )

    return AutomaticProvenanceCapture(
        repository_dirty=git["dirty"],
        provenance=provenance,
        limitations=tuple(limitations),
    )


def _capture_git(root: Path) -> dict[str, Any]:
    try:
        revision = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
        status = _git(
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        )
        tracked = _git(root, "ls-files", "-s", "-z")
        worktree_diff = _git(root, "diff", "--binary", "--no-ext-diff", "HEAD")
        staged_diff = _git(
            root,
            "diff",
            "--binary",
            "--no-ext-diff",
            "--cached",
            "HEAD",
        )
        untracked = _untracked_manifest(root)
        dirty = bool(status)
        material = {
                "revision": revision,
                "tracked_index_hash": sha256_bytes(tracked),
                "status_hash": sha256_bytes(status),
                "worktree_diff_hash": sha256_bytes(worktree_diff),
                "staged_diff_hash": sha256_bytes(staged_diff),
                "untracked": untracked,
            }
        observations = {key: base64.b64encode(value).decode("ascii") for key, value in {
            "tracked_index_hash": tracked, "status_hash": status,
            "worktree_diff_hash": worktree_diff, "staged_diff_hash": staged_diff,
        }.items()}
        return {"revision": revision, "code_hash": sha256(material), "dirty": dirty, "material": material, "observations": observations}
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError):
        manifest = _source_manifest(root)
        return {
            "revision": "unversioned-source",
            "code_hash": sha256(manifest),
            "dirty": True,
            "material": manifest,
        }


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    ).stdout


def _untracked_manifest(root: Path) -> tuple[tuple[str, str], ...]:
    raw = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    paths = sorted(item.decode("utf-8") for item in raw.split(b"\0") if item)
    entries: list[tuple[str, str]] = []
    total_bytes = 0
    for value in paths:
        relative = Path(value)
        if not _eligible_relative(relative):
            continue
        candidate = root / relative
        if candidate.is_symlink() or not candidate.is_file():
            continue
        if not _is_within_root(root, candidate):
            continue
        size = candidate.stat().st_size
        _check_capture_budget(
            file_count=len(entries) + 1,
            total_bytes=total_bytes + size,
            file_bytes=size,
            file_message="untracked source file exceeds the provenance capture limit",
        )
        entries.append((relative.as_posix(), _file_digest(candidate)))
        total_bytes += size
    return tuple(entries)


def _source_manifest(root: Path) -> tuple[tuple[str, str], ...]:
    entries: list[tuple[str, str]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root)
        if not _eligible_relative(relative) or not _is_within_root(root, path):
            continue
        size = path.stat().st_size
        _check_capture_budget(
            file_count=len(entries) + 1,
            total_bytes=total_bytes + size,
            file_bytes=size,
            file_message="source file exceeds the provenance capture limit",
        )
        entries.append((relative.as_posix(), _file_digest(path)))
        total_bytes += size
    if not entries:
        raise ValueError("repository_root contains no eligible source files")
    return tuple(entries)


def _environment_identity(root: Path) -> dict[str, object]:
    lockfiles: list[dict[str, str]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if path.name not in _LOCKFILE_NAMES:
            continue
        relative = path.relative_to(root)
        if not _eligible_relative(relative):
            continue
        if path.is_symlink() or not path.is_file() or not _is_within_root(root, path):
            raise ValueError("dependency lockfile must be a regular in-tree file")
        size = path.stat().st_size
        _check_capture_budget(
            file_count=len(lockfiles) + 1,
            total_bytes=total_bytes + size,
            file_bytes=size,
            file_message="dependency lockfile exceeds the provenance capture limit",
        )
        lockfiles.append(
            {"path": relative.as_posix(), "sha256": _file_digest(path)}
        )
        total_bytes += size

    packages = sorted(
        {
            (
                distribution.metadata.get("Name", "unknown").strip().lower(),
                distribution.version,
            )
            for distribution in importlib.metadata.distributions()
            if distribution.metadata.get("Name")
        }
    )
    return {
        "lockfiles": lockfiles,
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "abi": getattr(sys.implementation, "cache_tag", None),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "packages": [f"{name}=={version}" for name, version in packages],
    }


def _runtime_identity() -> dict[str, str]:
    implementation = platform.python_implementation().lower()
    version = platform.python_version()
    system = platform.system().lower() or "unknown"
    machine = platform.machine().lower() or "unknown"
    return {
        "label": f"{implementation}-{version}@{system}-{machine}",
        "implementation": implementation,
        "version": version,
        "system": system,
        "release": platform.release(),
        "machine": machine,
    }


def _source_refs(pack: StudyPack, pack_path: Path) -> tuple[ProvenanceSourceRef, ...]:
    refs: list[ProvenanceSourceRef] = [
        ProvenanceSourceRef(
            source_uri=f"study-pack://{pack.study_pack_id}@{pack.version}",
            content_hash=sha256(pack.model_dump(mode="json")),
        )
    ]

    preregistration = pack.preregistration
    _verify_declared_local_ref(
        pack_path.parent,
        preregistration.reference_uri,
        preregistration.content_hash,
    )
    refs.append(
        ProvenanceSourceRef(
            source_uri=f"study-pack-preregistration://{pack.study_pack_id}@{pack.version}/{preregistration.reference_uri}",
            content_hash=preregistration.content_hash,
        )
    )

    for scenario in sorted(pack.scenarios, key=lambda item: item.scenario_id):
        for source in sorted(
            scenario.evidence_sources,
            key=lambda item: (item.source_uri, item.content_hash),
        ):
            _verify_declared_local_ref(
                pack_path.parent,
                source.source_uri,
                source.content_hash,
            )
            refs.append(
                ProvenanceSourceRef(
                    source_uri=source.source_uri,
                    content_hash=source.content_hash,
                )
            )

    unique: dict[tuple[str, str], ProvenanceSourceRef] = {}
    for ref in refs:
        unique[(ref.source_uri, ref.content_hash)] = ref
    return tuple(unique[key] for key in sorted(unique))


def _verify_declared_local_ref(root: Path, uri: str, expected_hash: str) -> None:
    if "://" in uri:
        return
    declared = root / uri
    if declared.is_symlink():
        raise ValueError("StudyPack source reference must not be a symlink")
    candidate = declared.resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("StudyPack source reference escapes the pack root") from exc
    if not candidate.is_file():
        raise ValueError(f"StudyPack source reference is unavailable: {uri}")
    if _file_digest(candidate) != expected_hash:
        raise ValueError(f"StudyPack source reference digest mismatch: {uri}")


def _eligible_relative(relative: Path) -> bool:
    if relative.is_absolute() or ".." in relative.parts:
        return False
    folded_parts = tuple(part.casefold() for part in relative.parts)
    if any(part in _EXCLUDED_PARTS or part in _SENSITIVE_PARTS for part in folded_parts):
        return False
    name = relative.name.casefold()
    if name in _SENSITIVE_NAMES or name.startswith(".env."):
        return False
    return relative.suffix.casefold() not in _SENSITIVE_SUFFIXES


def _is_within_root(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def _check_capture_budget(
    *,
    file_count: int,
    total_bytes: int,
    file_bytes: int,
    file_message: str,
) -> None:
    if file_bytes > _MAX_CAPTURE_FILE_BYTES:
        raise ValueError(file_message)
    if file_count > _MAX_CAPTURE_FILES:
        raise ValueError("source manifest exceeds the provenance file-count limit")
    if total_bytes > _MAX_CAPTURE_TOTAL_BYTES:
        raise ValueError("source manifest exceeds the provenance total-byte limit")


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
