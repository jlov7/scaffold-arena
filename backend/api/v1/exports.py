"""Portable StudyPack export endpoint."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from api.public_errors import public_service_error
from services_v1 import (
    AnalysisExportService,
    AnalysisService,
    ExportError,
    StudyPackExportService,
)

router = APIRouter(prefix="/api/v1", tags=["protocol-v1-exports"])


def _service(request: Request) -> StudyPackExportService:
    service = getattr(request.app.state, "study_pack_export_service", None)
    if not isinstance(service, StudyPackExportService):
        raise ExportError(
            "exports_unavailable",
            "StudyPack export is not configured for this deployment.",
            status_code=503,
        )
    return service


def _project_id(request: Request) -> str | None:
    return request.headers.get("x-arena-project-id") or request.query_params.get(
        "project_id"
    )


def _error(exc: ExportError) -> JSONResponse:
    return public_service_error(exc)


async def _export_request(request: Request) -> Mapping[str, str]:
    try:
        body = await request.json()
    except Exception as exc:
        raise ExportError("invalid_json", "A JSON export request is required.") from exc
    if not isinstance(body, dict):
        raise ExportError(
            "invalid_export_request",
            "An explicit export kind is required.",
        )
    if body.get("kind") == "analysis" and set(body) == {"kind", "report_digest", "format"} and isinstance(body.get("report_digest"), str) and body.get("format") in {"csv", "parquet"}:
        return body
    if set(body) != {"kind", "study_pack_id", "version"}:
        raise ExportError("invalid_export_request", "Use exact fields for the selected export kind.")
    if (
        body.get("kind") != "study_pack"
        or not isinstance(body.get("study_pack_id"), str)
        or not isinstance(body.get("version"), str)
    ):
        raise ExportError(
            "invalid_export_request",
            "The export request must explicitly select kind='study_pack'.",
        )
    return body


@router.post("/exports")
async def export_study_pack(request: Request):
    try:
        body = await _export_request(request)
        if body["kind"] == "analysis":
            service = getattr(request.app.state, "analysis_export_service", None)
            if not isinstance(service, AnalysisExportService):
                analysis = getattr(request.app.state, "analysis_service", None)
                if isinstance(analysis, AnalysisService):
                    service = AnalysisExportService(
                        analysis.repository, analysis.artifact_store,
                        personal_project_id=analysis.personal_project_id,
                    )
                else:
                    raise ExportError("exports_unavailable", "Analysis export is not configured for this deployment.", status_code=503)
            exported = service.export_analysis(body["report_digest"], body["format"], project_id=_project_id(request))
            return Response(content=exported.content, media_type=exported.media_type, headers={
                "Content-Disposition": f'attachment; filename="{exported.filename}"',
                "X-Analysis-Report-Digest": exported.report_digest,
                "X-Analysis-Manifest-Hash": exported.manifest_hash,
                "X-Analysis-Export-Digest": exported.export_digest,
            })
        exported = _service(request).export_study_pack(
            body["study_pack_id"],
            body["version"],
            project_id=_project_id(request),
        )
        return Response(
            content=exported.content,
            media_type=exported.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{exported.filename}"',
                "X-Study-Pack-Content-Digest": exported.content_digest,
                "X-Study-Pack-Manifest-Hash": exported.manifest_hash,
                "X-Study-Pack-Export-Digest": exported.export_digest,
            },
        )
    except ExportError as exc:
        return _error(exc)
