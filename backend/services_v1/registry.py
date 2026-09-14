"""Non-executing registry services for the public protocol v1 boundary."""

from __future__ import annotations

import base64
import io
import json
import stat
import tempfile
import unicodedata
import uuid
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError
from sqlalchemy import insert, select

from adapters_v1 import AdapterRegistry
from artifacts_v1 import ArtifactStore
from persistence_v1 import (
    ArenaRepository,
    FrozenExperimentError,
    ImmutableVersionConflict,
)
from persistence_v1.schema import audit_events, experiments, study_packs
from protocol_v1 import (
    ExperimentSpec,
    StudyPack,
    assess_study_pack_readiness,
    canonical_json,
    expand_design,
    freeze_experiment,
    sha256,
)
from protocol_v1.canonical import sha256_bytes


class RegistryError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ParsedStudyPack:
    pack: StudyPack
    content: bytes
    content_media_type: str
    manifest: dict[str, Any]
    manifest_hash: str
    content_digest: str


_MAX_ZIP_FILES = 64
_MAX_ZIP_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
_MAX_ZIP_RATIO = 100
_DEFAULT_MAX_BODY_BYTES = 1_000_000
_MANIFEST = "study-pack.json"
_BUNDLE_MEDIA_TYPE = "application/vnd.scaffold-arena.study-pack-bundle+json"
_BUNDLE_FORMAT = "scaffold-arena-study-pack-bundle-v1"
_FORBIDDEN_SUFFIXES = {
    ".app", ".bash", ".bat", ".class", ".cmd", ".com", ".dll", ".dylib",
    ".exe", ".jar", ".js", ".mjs", ".php", ".pl", ".ps1", ".py", ".pyc",
    ".pyo", ".rb", ".sh", ".so", ".swift", ".ts", ".wasm", ".zsh",
}


class ProtocolRegistryService:
    """Registry-only policy layer. It never starts providers or adapters."""

    def __init__(
        self,
        repository: ArenaRepository,
        artifact_store: ArtifactStore,
        *,
        adapter_registry: AdapterRegistry | None = None,
        personal_project_id: str | None = None,
        max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES,
    ) -> None:
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive")
        self.repository = repository
        self.artifact_store = artifact_store
        self.adapter_registry = adapter_registry
        self.personal_project_id = personal_project_id
        self.max_body_bytes = max_body_bytes

    def resolve_project(self, project_id: str | None) -> str:
        resolved = project_id or self.personal_project_id
        if not resolved:
            raise RegistryError("project_context_required", "An explicit personal/local project context is required.", status_code=400)
        with self.repository.engine.connect() as conn:
            exists = conn.execute(select(study_packs.c.project_id).where(study_packs.c.project_id == resolved).limit(1)).scalar_one_or_none()
            if exists is None:
                # Empty projects are valid; check the projects table without inventing one.
                from persistence_v1.schema import projects

                if conn.execute(select(projects.c.id).where(projects.c.id == resolved)).scalar_one_or_none() is None:
                    raise RegistryError("unknown_project", "The supplied personal/local project does not exist.", status_code=404)
        return resolved

    def validate_pack(self, raw: bytes, media_type: str) -> dict[str, Any]:
        try:
            parsed = self._parse_pack(raw, media_type)
        except RegistryError as exc:
            if exc.status_code == 413:
                raise
            return {
                "valid": False,
                "errors": [{"code": exc.code, "message": "The study pack is invalid."}],
                "claim_ceiling": "no protocol claim; validation failed",
            }
        readiness = assess_study_pack_readiness(parsed.pack, claim_bearing=True)
        return {
            "valid": True,
            "canonical_manifest": parsed.manifest,
            "manifest_hash": parsed.manifest_hash,
            "content_digest": parsed.content_digest,
            "readiness": readiness.model_dump(mode="json"),
            "errors": [],
            "claim_ceiling": self._pack_claim_ceiling(parsed.pack, readiness.verdict),
        }

    def import_pack(self, raw: bytes, media_type: str, *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        parsed = self._parse_pack(raw, media_type)
        readiness = assess_study_pack_readiness(parsed.pack, claim_bearing=True)
        existing = self.repository.get_study_pack_version(project_id, parsed.pack.study_pack_id, parsed.pack.version)
        if existing is not None:
            if existing["content_digest"] != parsed.content_digest:
                raise RegistryError("immutable_version_conflict", "This study-pack version is already registered with different content.", status_code=409)
            self._verify_existing_artifact(existing, parsed.content)
            return self._pack_metadata(existing, idempotent_replay=True)

        digest = self.artifact_store.put_bytes(
            parsed.content,
            media_type=parsed.content_media_type,
            metadata={"kind": "study-pack", "manifest_hash": parsed.manifest_hash},
        )
        if digest != parsed.content_digest:
            raise RegistryError("artifact_integrity_error", "The study-pack artifact digest could not be verified.", status_code=500)
        pack_id = uuid.uuid4().hex
        metadata = {
            "manifest": parsed.manifest,
            "manifest_hash": parsed.manifest_hash,
            "title": parsed.pack.title,
            "license_spdx": parsed.pack.license_spdx,
            "authors": [author.model_dump(mode="json") for author in parsed.pack.authors],
            "allowed_claims": list(parsed.pack.allowed_claims),
            "limitations": list(parsed.pack.limitations),
            "content_media_type": parsed.content_media_type,
            "source_media_type": media_type.split(";", 1)[0].strip().lower(),
            "authority_ceiling": "personal/local protocol registry only",
            "readiness": readiness.model_dump(mode="json"),
        }
        try:
            with self.repository.transaction(immediate=True) as conn:
                artifact = conn.execute(select(study_packs.c.id).where(study_packs.c.project_id == project_id, study_packs.c.pack_key == parsed.pack.study_pack_id, study_packs.c.version == parsed.pack.version)).scalar_one_or_none()
                if artifact is not None:
                    raise ImmutableVersionConflict("study pack version already exists")
                from persistence_v1.schema import artifacts

                known_artifact = conn.execute(select(artifacts.c.digest).where(artifacts.c.digest == digest)).scalar_one_or_none()
                if known_artifact is None:
                    conn.execute(insert(artifacts).values(
                        digest=digest,
                        size_bytes=len(parsed.content),
                        storage_uri=self.artifact_store.uri_for(digest),
                        media_type=parsed.content_media_type,
                        metadata_json={"kind": "study-pack", "manifest_hash": parsed.manifest_hash},
                    ))
                conn.execute(insert(study_packs).values(
                    id=pack_id,
                    project_id=project_id,
                    pack_key=parsed.pack.study_pack_id,
                    version=parsed.pack.version,
                    content_digest=digest,
                    content_metadata=metadata,
                ))
                conn.execute(insert(audit_events).values(
                    id=uuid.uuid4().hex,
                    project_id=project_id,
                    event_type="study_pack_imported",
                    payload={"study_pack_id": pack_id, "pack_key": parsed.pack.study_pack_id, "version": parsed.pack.version, "content_digest": digest, "manifest_hash": parsed.manifest_hash},
                ))
        except ImmutableVersionConflict as exc:
            existing = self.repository.get_study_pack_version(project_id, parsed.pack.study_pack_id, parsed.pack.version)
            if existing is not None and existing["content_digest"] == digest:
                self._verify_existing_artifact(existing, parsed.content)
                return self._pack_metadata(existing, idempotent_replay=True)
            raise RegistryError("immutable_version_conflict", "This study-pack version is already registered with different content.", status_code=409) from exc
        except Exception as exc:
            # Do not surface database or filesystem detail through the public boundary.
            raise RegistryError("registry_write_failed", "The study pack could not be recorded.", status_code=500) from exc
        return self._pack_metadata(self.repository.get_study_pack_version(project_id, parsed.pack.study_pack_id, parsed.pack.version) or {}, idempotent_replay=False)

    def list_packs(self, *, project_id: str | None) -> list[dict[str, Any]]:
        project_id = self.resolve_project(project_id)
        with self.repository.engine.connect() as conn:
            rows = conn.execute(select(study_packs).where(study_packs.c.project_id == project_id).order_by(study_packs.c.pack_key, study_packs.c.version)).mappings().all()
        return [self._pack_metadata(row, idempotent_replay=False) for row in rows]

    def study_pack(self, pack_key: str, version: str, *, project_id: str | None) -> dict[str, Any]:
        """Return the exact registered declarative pack after custody verification."""
        project_id = self.resolve_project(project_id)
        row = self.repository.get_study_pack_version(project_id, pack_key, version)
        if row is None:
            raise RegistryError("study_pack_not_found", "The requested study-pack version was not found.", status_code=404)
        try:
            pack = self._load_pack_from_row(row)
        except RegistryError:
            raise RegistryError("study_pack_unavailable", "The registered study-pack cannot be read.", status_code=409) from None
        readiness = assess_study_pack_readiness(pack, claim_bearing=True)
        metadata = self._pack_metadata(row, idempotent_replay=False)
        return {
            "study_pack": metadata,
            "canonical_study_pack": pack.model_dump(mode="json"),
            "custody": {
                "content_digest": row["content_digest"],
                "manifest_hash": metadata["manifest_hash"],
                "artifact_integrity_verified": True,
            },
            "claim_ceiling": self._pack_claim_ceiling(pack, readiness.verdict),
            "authority_ceiling": "personal/local protocol registry only",
        }

    def list_experiments(
        self, *, project_id: str | None, study_pack_id: str | None = None, study_pack_version: str | None = None,
    ) -> list[dict[str, Any]]:
        project_id = self.resolve_project(project_id)
        statement = select(experiments, study_packs.c.pack_key, study_packs.c.version).join(
            study_packs, experiments.c.study_pack_id == study_packs.c.id,
        ).where(experiments.c.project_id == project_id)
        if study_pack_id is not None:
            statement = statement.where(study_packs.c.pack_key == study_pack_id)
        if study_pack_version is not None:
            statement = statement.where(study_packs.c.version == study_pack_version)
        with self.repository.engine.connect() as conn:
            rows = conn.execute(statement.order_by(experiments.c.created_at, experiments.c.id)).mappings().all()
        return [self._experiment_summary(row) for row in rows]

    def experiment(self, experiment_id: str, *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(experiments, study_packs.c.pack_key, study_packs.c.version).join(
                study_packs, experiments.c.study_pack_id == study_packs.c.id,
            ).where(experiments.c.id == experiment_id, experiments.c.project_id == project_id)).mappings().first()
        if row is None:
            raise RegistryError("experiment_not_found", "The requested experiment was not found.", status_code=404)
        result = self._experiment_summary(row)
        result["definition"] = dict(row["definition"] or {})
        result["immutable_identity"] = {
            "frozen": row["frozen_at"] is not None,
            "freeze_hash": row["spec_hash"],
            "study_pack_hash": row["study_pack_hash"],
            "frozen_at": row["frozen_at"],
        }
        return result

    def create_experiment(self, raw_spec: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        spec = self._parse_experiment(raw_spec)
        if spec.frozen:
            raise RegistryError("frozen_spec_rejected", "Create an unfrozen experiment definition, then use the freeze endpoint.")
        pack_row, pack = self._resolve_pack_for_spec(project_id, spec)
        predecessor = spec.predecessor_experiment_id
        try:
            self.repository.create_experiment(
                project_id,
                str(pack_row["id"]),
                spec.experiment_id,
                protocol_version=spec.protocol_version,
                predecessor_id=predecessor,
                owner_approval=spec.owner_approval,
                definition=spec.model_dump(mode="json"),
                experiment_id=spec.experiment_id,
            )
        except (ValueError, ImmutableVersionConflict) as exc:
            raise RegistryError("experiment_conflict", "The experiment identifier or predecessor relationship is not valid.", status_code=409) from exc
        except Exception as exc:
            raise RegistryError("experiment_write_failed", "The experiment could not be recorded.", status_code=500) from exc
        return self._experiment_response(spec.experiment_id, spec, pack_row, frozen=False, pack=pack)

    def freeze(self, experiment_id: str, *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        row = self._experiment_row(project_id, experiment_id)
        if row is None:
            raise RegistryError("experiment_not_found", "The requested experiment was not found.", status_code=404)
        if row["frozen_at"] is not None:
            frozen = self._validated_frozen_spec(row)
            return self._frozen_response(row, frozen, idempotent_replay=True)
        spec = self._parse_experiment(row["definition"])
        if row["owner_approval"] != "approved":
            raise RegistryError("owner_approval_required", "Freezing requires approval recorded on the stored experiment.", status_code=409)
        pack_row = self._pack_row_by_id(str(row["study_pack_id"]))
        if pack_row is None:
            raise RegistryError("study_pack_not_found", "The experiment's registered study pack was not found.", status_code=409)
        try:
            frozen = freeze_experiment(spec.model_copy(update={"owner_approval": "approved"}), str(pack_row["content_digest"]))
            self.repository.freeze_experiment(
                experiment_id,
                expected_definition=spec.model_dump(mode="json"),
                frozen_definition=frozen.model_dump(mode="json"),
                spec_hash=str(frozen.freeze_hash),
                study_pack_hash=str(pack_row["content_digest"]),
            )
        except (ValueError, FrozenExperimentError, TypeError) as exc:
            raise RegistryError("freeze_rejected", "The stored experiment cannot be frozen under the current protocol requirements.", status_code=409) from exc
        updated = self._experiment_row(project_id, experiment_id)
        return self._frozen_response(updated or row, frozen, idempotent_replay=False)

    def preflight(self, experiment_id: str, *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        row = self._experiment_row(project_id, experiment_id)
        if row is None:
            raise RegistryError("experiment_not_found", "The requested experiment was not found.", status_code=404)
        if row["frozen_at"] is None:
            spec = self._parse_experiment(row["definition"])
            frozen_state_valid = False
        else:
            spec = self._validated_frozen_spec(row)
            frozen_state_valid = True
        pack_row = self._pack_row_by_id(str(row["study_pack_id"]))
        if pack_row is None:
            raise RegistryError("study_pack_not_found", "The experiment's registered study pack was not found.", status_code=409)
        try:
            pack = self._load_pack_from_row(pack_row)
        except RegistryError:
            raise RegistryError("study_pack_unavailable", "The registered study pack cannot be read for preflight.", status_code=409) from None
        readiness = assess_study_pack_readiness(pack, claim_bearing=spec.claim_bearing)
        blockers: list[dict[str, str]] = [issue.model_dump() for issue in readiness.issues]
        if not frozen_state_valid:
            blockers.append(self._issue(
                "experiment_not_frozen",
                "experiment",
                "Preflight cannot PASS until the exact stored experiment definition is frozen.",
            ))
        try:
            arms = len(expand_design(spec))
        except ValueError:
            arms = 0
            blockers.append(self._issue("design_invalid", "experiment", "The experiment design cannot be expanded."))
        endpoint_count = max(len(spec.model_endpoints), 1)
        expected_attempts = arms * len(spec.scenario_ids) * len(spec.harness_ids) * endpoint_count * spec.repetitions
        self._preflight_budget(spec, expected_attempts, blockers)
        harnesses = {item.harness_id: item for item in pack.harnesses}
        for harness_id in spec.harness_ids:
            harness = harnesses[harness_id]
            self._preflight_harness(harness, spec, blockers)
        manipulation_checks = self._manipulation_check_summary(spec, pack)
        if not manipulation_checks["valid"]:
            blockers.append(self._issue(
                "manipulation_checks_missing",
                "experiment",
                "Required factor-level or scenario manipulation checks are missing.",
            ))
        if spec.claim_bearing:
            if not spec.primary_outcomes:
                blockers.append(self._issue("primary_outcomes_required", "experiment", "Claim-bearing preflight requires primary outcomes."))
            if not spec.model_endpoints:
                blockers.append(self._issue("endpoint_pins_required", "experiment", "Claim-bearing preflight requires pinned model endpoints."))
            elif any(endpoint.endpoint_digest is None for endpoint in spec.model_endpoints):
                blockers.append(self._issue("endpoint_pins_required", "experiment", "Every claim-bearing model endpoint requires a digest pin."))
        fixture_only = all(harnesses[item].claim_eligibility == "fixture_only" for item in spec.harness_ids)
        if not spec.claim_bearing and not fixture_only:
            blockers.append(self._issue("exploration_claim_ceiling", "experiment", "Non-claim-bearing preflight may PASS only for fixture exploration."))
        verdict = "PASS" if not blockers else "HOLD"
        claim_ceiling = "fixture exploration only; personal/local authority" if verdict == "PASS" and fixture_only else "personal/local protocol preflight only; no execution or evidence claim"
        return {
            "verdict": verdict,
            "blockers": blockers,
            "study_pack_readiness": readiness.model_dump(mode="json"),
            "design_expansion_count": arms,
            "expected_attempts": expected_attempts,
            "budget": self._budget_summary(spec, expected_attempts),
            "harnesses": [self._harness_summary(harnesses[item]) for item in spec.harness_ids],
            "manipulation_checks": manipulation_checks,
            "endpoint_pins": [
                {"endpoint_id": endpoint.endpoint_id, "pinned": endpoint.endpoint_digest is not None}
                for endpoint in spec.model_endpoints
            ],
            "provider_execution_started": False,
            "claim_ceiling": claim_ceiling,
            "authority_ceiling": "personal/local authority only; no authentication or OIDC claims are asserted",
        }

    def _parse_pack(self, raw: bytes, media_type: str) -> ParsedStudyPack:
        if len(raw) > self.max_body_bytes:
            raise RegistryError(
                "body_too_large",
                f"The study-pack body exceeds the {self.max_body_bytes}-byte limit.",
                status_code=413,
            )
        if not raw:
            raise RegistryError("empty_body", "A study-pack body is required.")
        normalized = media_type.split(";", 1)[0].strip().lower()
        if normalized == "application/zip":
            files = self._zip_files(raw)
        elif normalized in {"application/json", "application/study-pack+json", ""}:
            try:
                candidate = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RegistryError("invalid_json", "The study-pack JSON body is invalid.") from exc
            if not isinstance(candidate, dict):
                raise RegistryError("invalid_json", "A study-pack JSON object is required.")
            files = {_MANIFEST: raw}
        else:
            raise RegistryError("unsupported_media_type", "Use application/json or application/zip for study packs.", status_code=415)
        try:
            pack = StudyPack.model_validate_json(files[_MANIFEST])
        except (ValidationError, UnicodeDecodeError, ValueError) as exc:
            raise RegistryError("invalid_study_pack", "The declarative study pack does not satisfy protocol v1.") from exc
        files[_MANIFEST] = canonical_json(pack.model_dump(mode="json"))
        manifest = {
            "protocol_version": "1.0",
            "study_pack": pack.study_pack_id,
            "files": [
                {"path": path, "sha256": sha256_bytes(content), "size_bytes": len(content)}
                for path, content in sorted(files.items())
            ],
        }
        content = self._encode_bundle(files)
        return ParsedStudyPack(
            pack=pack,
            content=content,
            content_media_type=_BUNDLE_MEDIA_TYPE,
            manifest=manifest,
            manifest_hash=sha256(manifest),
            content_digest=sha256_bytes(content),
        )

    def _zip_files(self, raw: bytes) -> dict[str, bytes]:
        try:
            archive = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile as exc:
            raise RegistryError("invalid_zip", "The request body is not a valid ZIP archive.") from exc
        with archive, tempfile.TemporaryDirectory(prefix="scaffold-arena-pack-") as temporary_root:
            infos = archive.infolist()
            if not infos or len(infos) > _MAX_ZIP_FILES:
                raise RegistryError("zip_file_count", "The study-pack archive has an invalid number of files.")
            total = 0
            total_compressed = 0
            names: set[str] = set()
            paths: set[str] = set()
            validated: list[tuple[str, zipfile.ZipInfo]] = []
            for info in infos:
                path = self._safe_zip_path(info)
                folded = path.casefold()
                if folded in names:
                    raise RegistryError("zip_duplicate_path", "The study-pack archive contains duplicate normalized paths.")
                names.add(folded)
                paths.add(path)
                if info.flag_bits & 0x1:
                    raise RegistryError("zip_encrypted", "Encrypted study-pack archives are not accepted.")
                if info.file_size < 0 or info.compress_size < 0:
                    raise RegistryError("zip_invalid_entry", "The study-pack archive contains an invalid entry.")
                total += info.file_size
                total_compressed += info.compress_size
                if total > _MAX_ZIP_UNCOMPRESSED_BYTES:
                    raise RegistryError("zip_uncompressed_limit", "The study-pack archive expands beyond the allowed size.")
                if info.file_size and (info.compress_size == 0 or info.file_size / max(info.compress_size, 1) > _MAX_ZIP_RATIO):
                    raise RegistryError("zip_compression_ratio", "The study-pack archive exceeds the safe compression ratio.")
                validated.append((path, info))
            if total and (total_compressed == 0 or total / max(total_compressed, 1) > _MAX_ZIP_RATIO):
                raise RegistryError("zip_compression_ratio", "The study-pack archive exceeds the safe aggregate compression ratio.")
            if _MANIFEST not in paths:
                raise RegistryError("manifest_missing", "The study-pack archive requires study-pack.json.")
            extracted: dict[str, bytes] = {}
            root = Path(temporary_root).resolve()
            for path, info in validated:
                try:
                    content = archive.read(info)
                except (RuntimeError, zipfile.BadZipFile, NotImplementedError) as exc:
                    raise RegistryError("zip_entry_unreadable", "A study-pack archive entry cannot be read.") from exc
                if len(content) != info.file_size:
                    raise RegistryError("zip_size_mismatch", "A study-pack archive entry has inconsistent size metadata.")
                if path != _MANIFEST and self._looks_like_archive(content):
                    raise RegistryError("zip_nested_archive", "Nested archives are not permitted in study packs.")
                target = root.joinpath(*PurePosixPath(path).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                resolved_parent = target.parent.resolve()
                if root not in (resolved_parent, *resolved_parent.parents):
                    raise RegistryError("zip_path_unsafe", "The study-pack archive contains an unsafe path.")
                target.write_bytes(content)
                extracted[path] = target.read_bytes()
            return extracted

    @staticmethod
    def _safe_zip_path(info: zipfile.ZipInfo) -> str:
        name = unicodedata.normalize("NFC", info.filename.replace("\\", "/"))
        path = PurePosixPath(name)
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if (
            not name
            or "\x00" in name
            or name.endswith("/")
            or info.is_dir()
            or path.is_absolute()
            or ".." in path.parts
            or (path.parts and path.parts[0].endswith(":"))
        ):
            raise RegistryError("zip_path_unsafe", "The study-pack archive contains an unsafe path.")
        if kind not in {0, stat.S_IFREG}:
            raise RegistryError("zip_special_entry", "The study-pack archive contains a prohibited special entry.")
        if path.suffix.lower() in _FORBIDDEN_SUFFIXES:
            raise RegistryError("zip_executable_entry", "The study-pack archive contains an executable entry.")
        if path.name.lower().endswith((".zip", ".tar", ".tgz", ".tar.gz", ".gz", ".bz2", ".xz", ".7z", ".rar")):
            raise RegistryError("zip_nested_archive", "Nested archives are not permitted in study packs.")
        return path.as_posix()

    @staticmethod
    def _looks_like_archive(content: bytes) -> bool:
        return (
            content.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08", b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00", b"7z\xbc\xaf'\x1c"))
            or len(content) > 262
            and content[257:262] == b"ustar"
        )

    @staticmethod
    def _encode_bundle(files: Mapping[str, bytes]) -> bytes:
        return canonical_json({
            "format": _BUNDLE_FORMAT,
            "files": [
                {"path": path, "content_base64": base64.b64encode(content).decode("ascii")}
                for path, content in sorted(files.items())
            ],
        })

    @staticmethod
    def _decode_bundle(content: bytes) -> dict[str, bytes]:
        try:
            payload = json.loads(content)
            entries = payload["files"]
            if payload.get("format") != _BUNDLE_FORMAT or not isinstance(entries, list):
                raise ValueError("invalid normalized bundle")
            files: dict[str, bytes] = {}
            for entry in entries:
                path = entry["path"]
                if not isinstance(path, str) or path in files:
                    raise ValueError("invalid normalized bundle path")
                files[path] = base64.b64decode(entry["content_base64"], validate=True)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RegistryError("stored_bundle_invalid", "The stored study-pack bundle is invalid.", status_code=409) from exc
        if _MANIFEST not in files or ProtocolRegistryService._encode_bundle(files) != content:
            raise RegistryError("stored_bundle_noncanonical", "The stored study-pack bundle is not canonical.", status_code=409)
        return files

    def _resolve_pack_for_spec(self, project_id: str, spec: ExperimentSpec) -> tuple[Mapping[str, Any], StudyPack]:
        with self.repository.engine.connect() as conn:
            rows = conn.execute(select(study_packs).where(study_packs.c.project_id == project_id, study_packs.c.pack_key == spec.study_pack_id)).mappings().all()
        if not rows:
            raise RegistryError("study_pack_not_imported", "The experiment references a study pack that has not been imported.", status_code=409)
        if len(rows) != 1:
            raise RegistryError("study_pack_version_ambiguous", "The experiment must reference a uniquely imported study-pack version.", status_code=409)
        row = rows[0]
        try:
            pack = self._load_pack_from_row(row)
        except RegistryError:
            raise RegistryError("study_pack_unavailable", "The registered study pack cannot be read.", status_code=409) from None
        if not set(spec.scenario_ids).issubset({item.scenario_id for item in pack.scenarios}) or not set(spec.harness_ids).issubset({item.harness_id for item in pack.harnesses}):
            raise RegistryError("cross_pack_reference", "The experiment references scenarios or harnesses outside its imported study pack.", status_code=409)
        return dict(row), pack

    def _load_pack_from_row(self, row: Mapping[str, Any]) -> StudyPack:
        try:
            content = self.artifact_store.get_bytes(str(row["content_digest"]))
            if sha256_bytes(content) != row["content_digest"]:
                raise RegistryError("artifact_integrity_error", "The stored study-pack digest cannot be verified.", status_code=409)
            files = self._decode_bundle(content)
            pack = StudyPack.model_validate_json(files[_MANIFEST])
            if canonical_json(pack.model_dump(mode="json")) != files[_MANIFEST]:
                raise RegistryError("stored_manifest_noncanonical", "The stored study-pack manifest is not canonical.", status_code=409)
            return pack
        except (OSError, ValueError, RegistryError) as exc:
            raise RegistryError("study_pack_unavailable", "The registered study pack cannot be read.", status_code=409) from exc

    def _verify_existing_artifact(self, row: Mapping[str, Any], expected_content: bytes) -> None:
        try:
            stored = self.artifact_store.get_bytes(str(row["content_digest"]))
        except Exception as exc:
            raise RegistryError("artifact_integrity_error", "The existing study-pack artifact cannot be verified.", status_code=409) from exc
        if sha256_bytes(stored) != row["content_digest"] or stored != expected_content:
            raise RegistryError("artifact_integrity_error", "The existing study-pack artifact does not match its registry digest.", status_code=409)
        self._decode_bundle(stored)

    @staticmethod
    def _parse_experiment(raw_spec: Mapping[str, Any]) -> ExperimentSpec:
        try:
            # JSON is the public transport; Pydantic's JSON mode faithfully maps
            # JSON arrays onto the protocol's immutable tuple fields.
            return ExperimentSpec.model_validate_json(canonical_json(raw_spec))
        except ValidationError as exc:
            raise RegistryError("invalid_experiment", "The experiment definition does not satisfy protocol v1.") from exc

    def _experiment_row(self, project_id: str, experiment_id: str) -> Mapping[str, Any] | None:
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(experiments).where(experiments.c.id == experiment_id, experiments.c.project_id == project_id)).mappings().first()
        return dict(row) if row else None

    def _validated_frozen_spec(self, row: Mapping[str, Any]) -> ExperimentSpec:
        try:
            spec = self._parse_experiment(row["definition"])
        except RegistryError as exc:
            raise RegistryError(
                "frozen_state_mismatch",
                "The persisted frozen experiment definition is invalid; preflight remains HOLD.",
                status_code=409,
            ) from exc
        scalar_time = row.get("frozen_at")
        spec_time = spec.frozen_at
        if scalar_time is not None and scalar_time.tzinfo is None:
            scalar_time = scalar_time.replace(tzinfo=UTC)
        consistent = (
            spec.frozen is True
            and spec.freeze_hash == row.get("spec_hash")
            and spec.study_pack_hash == row.get("study_pack_hash")
            and spec_time is not None
            and scalar_time is not None
            and spec_time.astimezone(UTC) == scalar_time.astimezone(UTC)
            and spec.owner_approval == row.get("owner_approval") == "approved"
        )
        if not consistent:
            raise RegistryError(
                "frozen_state_mismatch",
                "The persisted frozen experiment definition and scalar bindings disagree; preflight remains HOLD.",
                status_code=409,
            )
        return spec

    def _pack_row_by_id(self, pack_id: str) -> Mapping[str, Any] | None:
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(study_packs).where(study_packs.c.id == pack_id)).mappings().first()
        return dict(row) if row else None

    @staticmethod
    def _pack_metadata(row: Mapping[str, Any], *, idempotent_replay: bool) -> dict[str, Any]:
        metadata = dict(row.get("content_metadata") or {})
        readiness = metadata.get("readiness")
        if not isinstance(readiness, Mapping):
            readiness = {
                "protocol_version": "1.0",
                "verdict": "HOLD",
                "task_family_deterministic_weights": {},
                "issues": [{
                    "code": "readiness-unavailable",
                    "scope": "registry",
                    "message": "Stored readiness is unavailable; run preflight before treating this pack as ready.",
                }],
            }
        return {
            "id": row.get("id"), "study_pack_id": row.get("pack_key"), "version": row.get("version"),
            "content_digest": row.get("content_digest"), "manifest_hash": metadata.get("manifest_hash"),
            "title": metadata.get("title"), "license_spdx": metadata.get("license_spdx"),
            "authors": metadata.get("authors", []), "allowed_claims": metadata.get("allowed_claims", []),
            "limitations": metadata.get("limitations", []), "created_at": row.get("created_at"),
            "authority_ceiling": "personal/local protocol registry only", "idempotent_replay": idempotent_replay,
            "readiness": readiness,
        }

    @staticmethod
    def _experiment_summary(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "experiment_id": row["id"], "study_pack_registry_id": row["study_pack_id"],
            "study_pack_id": row["pack_key"], "study_pack_version": row["version"],
            "protocol_version": row["protocol_version"], "predecessor_id": row["predecessor_id"],
            "owner_approval": row["owner_approval"], "frozen": row["frozen_at"] is not None,
            "freeze_hash": row["spec_hash"], "study_pack_hash": row["study_pack_hash"],
            "frozen_at": row["frozen_at"], "created_at": row["created_at"],
            "authority_ceiling": "personal/local authority only; no authentication or OIDC claims are asserted",
        }

    @staticmethod
    def _pack_claim_ceiling(pack: StudyPack, readiness: str) -> str:
        if readiness == "PASS":
            return "protocol readiness only; personal/local authority; no execution evidence"
        return "protocol validation only; readiness HOLD; no execution evidence"

    @staticmethod
    def _experiment_response(experiment_id: str, spec: ExperimentSpec, pack_row: Mapping[str, Any], *, frozen: bool, pack: StudyPack) -> dict[str, Any]:
        del pack
        return {
            "experiment_id": experiment_id, "study_pack_id": spec.study_pack_id, "study_pack_registry_id": pack_row["id"],
            "predecessor_id": spec.predecessor_experiment_id, "owner_approval": spec.owner_approval,
            "frozen": frozen, "definition": spec.model_dump(mode="json"),
            "authority_ceiling": "personal/local authority only; no authentication or OIDC claims are asserted",
        }

    @staticmethod
    def _frozen_response(row: Mapping[str, Any], spec: ExperimentSpec, *, idempotent_replay: bool) -> dict[str, Any]:
        return {
            "experiment_id": row["id"], "frozen": True, "freeze_hash": row["spec_hash"],
            "study_pack_hash": row["study_pack_hash"], "frozen_at": row["frozen_at"],
            "owner_approval": row["owner_approval"], "idempotent_replay": idempotent_replay,
            "authority_ceiling": "personal/local authority only; no authentication or OIDC claims are asserted",
        }

    @staticmethod
    def _issue(code: str, scope: str, message: str) -> dict[str, str]:
        return {"code": code, "scope": scope, "message": message}

    def _preflight_budget(self, spec: ExperimentSpec, expected: int, blockers: list[dict[str, str]]) -> None:
        if spec.budgets is None:
            blockers.append(self._issue("per_attempt_budget_required", "budget", "A per-attempt budget is required."))
        if spec.aggregate_budget is None:
            blockers.append(self._issue("aggregate_budget_required", "budget", "An aggregate budget is required."))
            return
        aggregate = spec.aggregate_budget
        if aggregate.max_attempts < expected:
            blockers.append(self._issue("aggregate_attempts_insufficient", "budget", "Aggregate max_attempts is below the expanded design requirement."))
        if spec.budgets is not None:
            per = spec.budgets
            if aggregate.max_total_cost_usd < expected * per.max_cost_usd:
                blockers.append(self._issue("aggregate_cost_insufficient", "budget", "Aggregate cost budget is below the expanded per-attempt maximum."))
            if aggregate.max_total_tokens < expected * per.max_tokens:
                blockers.append(self._issue("aggregate_tokens_insufficient", "budget", "Aggregate token budget is below the expanded per-attempt maximum."))
            if aggregate.max_total_tool_calls < expected * per.max_tool_calls:
                blockers.append(self._issue("aggregate_tools_insufficient", "budget", "Aggregate tool-call budget is below the expanded per-attempt maximum."))
            if aggregate.max_wall_time_seconds < expected * per.max_latency_seconds:
                blockers.append(self._issue("aggregate_time_insufficient", "budget", "Aggregate wall-time budget is below the expanded per-attempt maximum."))

    def _preflight_harness(self, harness: Any, spec: ExperimentSpec, blockers: list[dict[str, str]]) -> None:
        if harness.effective_configuration_hash is not None and harness.effective_configuration_hash != sha256(harness.configuration):
            blockers.append(self._issue("harness_config_hash_mismatch", harness.harness_id, "Harness configuration hash does not match its configuration."))
        if spec.claim_bearing and harness.claim_eligibility == "fixture_only":
            blockers.append(self._issue("fixture_harness_claim_ineligible", harness.harness_id, "Fixture-only harness cannot support a claim-bearing preflight."))
        if spec.claim_bearing and (harness.capabilities.tools or harness.capabilities.state) and harness.isolation not in {"container", "remote_sandbox"}:
            blockers.append(self._issue("harness_isolation_ineligible", harness.harness_id, "Tool or state-capable claim harness requires container or remote sandbox isolation."))
        if self.adapter_registry is not None:
            if harness.adapter_identity is None or harness.adapter_digest is None:
                blockers.append(self._issue("trusted_adapter_missing", harness.harness_id, "Harness does not bind a trusted adapter identity and digest."))
            else:
                try:
                    self.adapter_registry.get(harness.adapter_identity, harness.adapter_digest)
                    capability_lookup = getattr(self.adapter_registry, "capabilities", None)
                    if not callable(capability_lookup):
                        return
                    capabilities = capability_lookup(harness.adapter_identity, harness.adapter_digest)
                    if capabilities.adapter_kind != harness.adapter:
                        blockers.append(self._issue("adapter_kind_mismatch", harness.harness_id, "The installed adapter kind differs from the harness declaration."))
                    if harness.isolation not in capabilities.supported_isolation:
                        blockers.append(self._issue("adapter_isolation_mismatch", harness.harness_id, "The installed adapter does not support the requested isolation."))
                    eligibility = ("fixture_only", "protocol_only", "live_provider", "externally_validated")
                    if eligibility.index(harness.claim_eligibility) > eligibility.index(capabilities.claim_eligibility):
                        blockers.append(self._issue("adapter_claim_ceiling_mismatch", harness.harness_id, "The installed adapter cannot support the requested claim eligibility."))
                    for name in type(harness.capabilities).model_fields:
                        if getattr(harness.capabilities, name) and not getattr(capabilities.capabilities, name):
                            blockers.append(self._issue("adapter_capability_mismatch", harness.harness_id, f"The installed adapter lacks required {name} capability."))
                except (KeyError, ValueError):
                    blockers.append(self._issue("trusted_adapter_missing", harness.harness_id, "The declared adapter is not trusted and installed."))

    @staticmethod
    def _manipulation_check_summary(spec: ExperimentSpec, pack: StudyPack) -> dict[str, Any]:
        declared = tuple(spec.manipulation_checks) + tuple(
            check for factor in spec.factors for check in factor.manipulation_checks
        )
        declared_keys = {
            (check.factor_id, json.dumps(check.expected_value, sort_keys=True), check.oracle)
            for check in declared
        }
        scenarios = {scenario.scenario_id: scenario for scenario in pack.scenarios}
        required_scenario_checks = tuple(
            check
            for scenario_id in spec.scenario_ids
            for check in scenarios[scenario_id].manipulation_checks
        )
        missing_scenario_checks = [
            check.model_dump(mode="json")
            for check in required_scenario_checks
            if (check.factor_id, json.dumps(check.expected_value, sort_keys=True), check.oracle) not in declared_keys
        ]
        varied_factor_ids = {factor.factor_id for factor in spec.factors}
        declared_factor_ids = {check.factor_id for check in declared}
        missing_factor_ids = sorted(varied_factor_ids - declared_factor_ids)
        return {
            "varied_factor_ids": sorted(varied_factor_ids),
            "declared_check_factor_ids": sorted(declared_factor_ids),
            "required_scenario_checks": [check.model_dump(mode="json") for check in required_scenario_checks],
            "missing_required_checks": missing_scenario_checks,
            "missing_factor_ids": missing_factor_ids,
            "valid": not missing_factor_ids and not missing_scenario_checks,
        }

    @staticmethod
    def _budget_summary(spec: ExperimentSpec, expected: int) -> dict[str, Any]:
        return {
            "expected_attempts": expected,
            "per_attempt": spec.budgets.model_dump(mode="json") if spec.budgets else None,
            "aggregate": spec.aggregate_budget.model_dump(mode="json") if spec.aggregate_budget else None,
        }

    def _harness_summary(self, harness: Any) -> dict[str, Any]:
        trusted = None
        if self.adapter_registry is not None and harness.adapter_identity and harness.adapter_digest:
            try:
                self.adapter_registry.get(harness.adapter_identity, harness.adapter_digest)
                trusted = True
            except (KeyError, ValueError):
                trusted = False
        return {
            "harness_id": harness.harness_id, "adapter": harness.adapter, "adapter_identity": harness.adapter_identity,
            "adapter_digest": harness.adapter_digest, "trusted_adapter_present": trusted,
            "capabilities": harness.capabilities.model_dump(mode="json"), "isolation": harness.isolation,
            "configuration_hash": harness.effective_configuration_hash, "claim_eligibility": harness.claim_eligibility,
        }
