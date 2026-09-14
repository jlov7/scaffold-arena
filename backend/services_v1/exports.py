"""Portable, non-executing StudyPack exports from verified local artifacts."""

from __future__ import annotations

import base64
import io
import json
import stat
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from analysis_v1 import AnalysisReport
from artifacts_v1 import ArtifactStore
from persistence_v1 import ArenaRepository
from persistence_v1.schema import analysis_reports, projects, study_packs
from protocol_v1 import StudyPack, canonical_json, sha256
from protocol_v1.canonical import sha256_bytes


class ExportError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ExportedStudyPack:
    content: bytes
    filename: str
    media_type: str
    study_pack_id: str
    version: str
    content_digest: str
    manifest_hash: str
    export_digest: str


@dataclass(frozen=True)
class ExportedAnalysis:
    content: bytes
    filename: str
    media_type: str
    report_digest: str
    manifest_hash: str
    export_digest: str


_BUNDLE_FORMAT = "scaffold-arena-study-pack-bundle-v1"
_MANIFEST = "study-pack.json"
_FORBIDDEN_SUFFIXES = frozenset(
    {
        ".app",
        ".bash",
        ".bat",
        ".class",
        ".cmd",
        ".com",
        ".dll",
        ".dylib",
        ".exe",
        ".jar",
        ".js",
        ".mjs",
        ".php",
        ".pl",
        ".ps1",
        ".py",
        ".pyc",
        ".pyo",
        ".rb",
        ".sh",
        ".so",
        ".swift",
        ".ts",
        ".wasm",
        ".zsh",
    }
)
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "bearer_token",
        "credential",
        "credentials",
        "password",
        "refresh_token",
        "secret",
        "access_token",
        "client_secret",
        "private_key",
    }
)


class AnalysisExportService:
    """Regenerates analysis-ready exports from one immutable report artifact."""

    def __init__(self, repository: ArenaRepository, artifact_store: ArtifactStore, *, personal_project_id: str | None = None) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.personal_project_id = personal_project_id

    def export_analysis(self, report_digest: str, format: str, *, project_id: str | None) -> ExportedAnalysis:
        project_id = self._project(project_id)
        if format not in {"csv", "parquet"}:
            raise ExportError("invalid_analysis_export_format", "Analysis exports support exactly csv or parquet.")
        with self.repository.engine.connect() as conn:
            row = conn.execute(select(analysis_reports).where(
                analysis_reports.c.project_id == project_id,
                analysis_reports.c.report_digest == report_digest,
            )).mappings().first()
        if row is None:
            raise ExportError("analysis_report_not_found", "The immutable analysis report was not found in this project.", status_code=404)
        raw = self.artifact_store.get_bytes(str(row["artifact_digest"]))
        if sha256_bytes(raw) != report_digest:
            raise ExportError("analysis_artifact_integrity_error", "The analysis artifact digest does not match the immutable report.", status_code=409)
        try:
            report = AnalysisReport.model_validate_json(raw)
        except ValueError as exc:
            raise ExportError("analysis_artifact_invalid", "The analysis artifact is not a valid frozen report.", status_code=409) from exc
        rows = _analysis_rows(report, report_digest)
        content, media_type, suffix = _analysis_content(rows, format)
        manifest = {
            "format": f"analysis-ready-{format}-v1",
            "report_digest": report_digest,
            "row_count": len(rows),
            "content_digest": sha256_bytes(content),
        }
        return ExportedAnalysis(
            content=content,
            filename=f"analysis-{report_digest[:12]}.{suffix}",
            media_type=media_type,
            report_digest=report_digest,
            manifest_hash=sha256(manifest),
            export_digest=sha256_bytes(content),
        )

    def _project(self, project_id: str | None) -> str:
        resolved = project_id or self.personal_project_id
        if not resolved:
            raise ExportError("project_context_required", "An explicit project context is required.")
        with self.repository.engine.connect() as conn:
            exists = conn.execute(select(projects.c.id).where(projects.c.id == resolved)).scalar_one_or_none()
        if exists is None:
            raise ExportError("unknown_project", "The supplied project does not exist.", status_code=404)
        return resolved


def _analysis_rows(report: AnalysisReport, report_digest: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for effect in (*report.main_effects, *report.secondary_interactions, *report.clean_vs_stressed_tax):
        rows.append({
            "report_digest": report_digest,
            "record_type": effect.kind,
            "record_id": effect.effect_id,
            "outcome": effect.outcome,
            "status": effect.status,
            "estimate": "" if effect.estimate is None else repr(effect.estimate),
            "ci_low": "" if effect.confidence_interval[0] is None else repr(effect.confidence_interval[0]),
            "ci_high": "" if effect.confidence_interval[1] is None else repr(effect.confidence_interval[1]),
            "attempt_ids": "|".join(effect.series.attempt_ids),
            "constituent_attempt_ids": "|".join(effect.series.constituent_attempt_ids),
        })
    return sorted(rows, key=lambda item: (item["record_type"], item["record_id"]))


def _analysis_content(rows: list[dict[str, str]], format: str) -> tuple[bytes, str, str]:
    columns = ("report_digest", "record_type", "record_id", "outcome", "status", "estimate", "ci_low", "ci_high", "attempt_ids", "constituent_attempt_ids")
    if format == "csv":
        output = io.StringIO(newline="")
        writer = __import__("csv").DictWriter(output, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows({
            **row,
            "record_id": _csv_safe_text(row["record_id"]),
            "outcome": _csv_safe_text(row["outcome"]),
            "attempt_ids": _csv_safe_text(row["attempt_ids"]),
            "constituent_attempt_ids": _csv_safe_text(row["constituent_attempt_ids"]),
        } for row in rows)
        return output.getvalue().encode("utf-8"), "text/csv; charset=utf-8", "csv"
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ExportError("research_extra_unavailable", "Parquet export requires the research optional dependency group.", status_code=409) from exc
    output = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema([(name, pa.string()) for name in columns])), output, compression=None, version="2.6")
    return output.getvalue(), "application/vnd.apache.parquet", "parquet"


def _csv_safe_text(value: str) -> str:
    if value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


class StudyPackExportService:
    """Exports only a registered pack's exact declarative source files.

    The service performs no registry writes. A successful export is a deterministic
    ZIP representation of the already content-addressed import, not a new result,
    provenance record, executable package, or claim-bearing artifact.
    """

    def __init__(
        self,
        repository: ArenaRepository,
        artifact_store: ArtifactStore,
        *,
        personal_project_id: str | None = None,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.personal_project_id = personal_project_id

    def resolve_project(self, project_id: str | None) -> str:
        resolved = project_id or self.personal_project_id
        if not resolved:
            raise ExportError(
                "project_context_required", "An explicit project context is required."
            )
        with self.repository.engine.connect() as conn:
            exists = conn.execute(
                select(projects.c.id).where(projects.c.id == resolved)
            ).scalar_one_or_none()
        if exists is None:
            raise ExportError(
                "unknown_project",
                "The supplied project does not exist.",
                status_code=404,
            )
        return resolved

    def export_study_pack(
        self,
        study_pack_id: str,
        version: str,
        *,
        project_id: str | None,
    ) -> ExportedStudyPack:
        project_id = self.resolve_project(project_id)
        row = self._pack_row(project_id, study_pack_id, version)
        if row is None:
            raise ExportError(
                "study_pack_not_found",
                "The requested StudyPack is not registered in this project.",
                status_code=404,
            )
        files, pack, _manifest, manifest_hash = self._verified_files(row)
        content = self._canonical_zip(files)
        return ExportedStudyPack(
            content=content,
            filename=f"study-pack-{pack.study_pack_id}-{pack.version}.zip",
            media_type="application/zip",
            study_pack_id=pack.study_pack_id,
            version=pack.version,
            content_digest=str(row["content_digest"]),
            manifest_hash=manifest_hash,
            export_digest=sha256_bytes(content),
        )

    def _pack_row(
        self, project_id: str, study_pack_id: str, version: str
    ) -> Mapping[str, Any] | None:
        with self.repository.engine.connect() as conn:
            row = (
                conn.execute(
                    select(study_packs).where(
                        study_packs.c.project_id == project_id,
                        study_packs.c.pack_key == study_pack_id,
                        study_packs.c.version == version,
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def _verified_files(
        self, row: Mapping[str, Any]
    ) -> tuple[dict[str, bytes], StudyPack, dict[str, Any], str]:
        digest = str(row["content_digest"])
        try:
            content = self.artifact_store.get_bytes(digest)
        except Exception as exc:
            raise ExportError(
                "artifact_unavailable",
                "The registered StudyPack artifact cannot be read.",
                status_code=409,
            ) from exc
        if sha256_bytes(content) != digest:
            raise ExportError(
                "artifact_integrity_error",
                "The registered StudyPack artifact digest does not match.",
                status_code=409,
            )
        files = self._decode_canonical_bundle(content)
        self._validate_files(files)
        try:
            pack = StudyPack.model_validate_json(files[_MANIFEST])
        except (UnicodeDecodeError, ValueError) as exc:
            raise ExportError(
                "stored_manifest_invalid",
                "The stored StudyPack manifest is invalid.",
                status_code=409,
            ) from exc
        canonical_manifest = canonical_json(pack.model_dump(mode="json"))
        if files[_MANIFEST] != canonical_manifest:
            raise ExportError(
                "stored_manifest_noncanonical",
                "The stored StudyPack manifest is not canonical.",
                status_code=409,
            )
        if pack.study_pack_id != row["pack_key"] or pack.version != row["version"]:
            raise ExportError(
                "registry_binding_mismatch",
                "The registered StudyPack identity does not match its artifact.",
                status_code=409,
            )
        manifest = self._manifest_for(files, pack.study_pack_id)
        manifest_hash = sha256(manifest)
        metadata = dict(row.get("content_metadata") or {})
        if (
            metadata.get("manifest") != manifest
            or metadata.get("manifest_hash") != manifest_hash
        ):
            raise ExportError(
                "manifest_integrity_error",
                "The registered StudyPack manifest binding does not match its artifact.",
                status_code=409,
            )
        self._reject_secret_fields(files)
        return files, pack, manifest, manifest_hash

    @staticmethod
    def _decode_canonical_bundle(content: bytes) -> dict[str, bytes]:
        try:
            payload = json.loads(content)
            entries = payload["files"]
            if payload.get("format") != _BUNDLE_FORMAT or not isinstance(entries, list):
                raise ValueError("invalid bundle")
            files: dict[str, bytes] = {}
            for entry in entries:
                path = entry["path"]
                if not isinstance(path, str) or path in files:
                    raise ValueError("invalid bundle path")
                files[path] = base64.b64decode(entry["content_base64"], validate=True)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExportError(
                "stored_bundle_invalid",
                "The stored StudyPack bundle is invalid.",
                status_code=409,
            ) from exc
        if StudyPackExportService._encode_bundle(files) != content:
            raise ExportError(
                "stored_bundle_noncanonical",
                "The stored StudyPack bundle is not canonical.",
                status_code=409,
            )
        return files

    @staticmethod
    def _encode_bundle(files: Mapping[str, bytes]) -> bytes:
        return canonical_json(
            {
                "format": _BUNDLE_FORMAT,
                "files": [
                    {
                        "path": path,
                        "content_base64": base64.b64encode(body).decode("ascii"),
                    }
                    for path, body in sorted(files.items())
                ],
            }
        )

    @staticmethod
    def _manifest_for(files: Mapping[str, bytes], study_pack_id: str) -> dict[str, Any]:
        return {
            "protocol_version": "1.0",
            "study_pack": study_pack_id,
            "files": [
                {"path": path, "sha256": sha256_bytes(body), "size_bytes": len(body)}
                for path, body in sorted(files.items())
            ],
        }

    @staticmethod
    def _validate_files(files: Mapping[str, bytes]) -> None:
        if _MANIFEST not in files:
            raise ExportError(
                "stored_manifest_missing",
                "The stored StudyPack bundle is missing study-pack.json.",
                status_code=409,
            )
        for path in files:
            parts = path.split("/")
            if (
                not path
                or path.startswith("/")
                or "\\" in path
                or any(part in {"", ".", ".."} for part in parts)
                or path.rsplit("/", 1)[-1].lower().endswith(tuple(_FORBIDDEN_SUFFIXES))
            ):
                raise ExportError(
                    "stored_bundle_unsafe",
                    "The stored StudyPack contains a prohibited file path.",
                    status_code=409,
                )

    @staticmethod
    def _reject_secret_fields(files: Mapping[str, bytes]) -> None:
        for path, content in files.items():
            try:
                payload = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if StudyPackExportService._contains_secret_field(payload):
                raise ExportError(
                    "secret_field_present",
                    f"The stored StudyPack contains a secret-bearing JSON field ({path}).",
                    status_code=409,
                )

    @staticmethod
    def _contains_secret_field(value: Any) -> bool:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key).strip().lower().replace("-", "_")
                if normalized in _SECRET_KEYS or normalized.endswith(
                    ("_secret", "_password")
                ):
                    return True
                if StudyPackExportService._contains_secret_field(nested):
                    return True
        elif isinstance(value, list):
            return any(
                StudyPackExportService._contains_secret_field(item) for item in value
            )
        return False

    @staticmethod
    def _canonical_zip(files: Mapping[str, bytes]) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(
            output, mode="w", compression=zipfile.ZIP_STORED, strict_timestamps=True
        ) as archive:
            for path, content in sorted(files.items()):
                entry = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = (stat.S_IFREG | 0o644) << 16
                entry.compress_type = zipfile.ZIP_STORED
                archive.writestr(entry, content)
        return output.getvalue()
