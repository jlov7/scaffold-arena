from __future__ import annotations

import json

import pytest
from sqlalchemy import insert

from artifacts_v1 import LocalArtifactStore
from observatory_v1 import ObservatoryReport, ObservatoryRequest
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.schema import attempts, episodes, executions, experiments, study_packs
from services_v1 import ObservatoryError, ObservatoryService, XrayError, XrayService
from xray_v1 import XRayReport, XRayRequest


def _repository(tmp_path) -> tuple[ArenaRepository, LocalArtifactStore]:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    return repository, LocalArtifactStore(tmp_path / "artifacts")


def _register(repository: ArenaRepository, store: LocalArtifactStore, content: bytes) -> str:
    digest = store.put_bytes(content, media_type="application/json")
    repository.register_artifact(
        digest,
        size_bytes=len(content),
        storage_uri=store.uri_for(digest),
        media_type="application/json",
    )
    return digest


def _xray_source() -> bytes:
    return json.dumps(
        {
            "components": [{"component_id": "memory-core", "kind": "memory"}],
            "findings": [
                {"finding_id": "declared-one", "evidence_state": "declared", "subject": "private-secret", "statement": "must not leave the report", "evidence_refs": ["private-ref"]},
                {"finding_id": "observed-one", "evidence_state": "observed", "subject": "private-secret", "statement": "must not leave the report", "evidence_refs": ["private-ref"]},
                {"finding_id": "inferred-one", "evidence_state": "inferred", "subject": "private-secret", "statement": "must not leave the report", "evidence_refs": ["private-ref"], "inference_basis": "bounded declaration pattern"},
                {"finding_id": "verified-one", "evidence_state": "verified", "subject": "private-secret", "statement": "must not leave the report", "evidence_refs": ["private-ref"], "verification_method": "recorded checker receipt"},
                {"finding_id": "unsupported-one", "evidence_state": "unsupported", "subject": "private-secret", "statement": "must not leave the report", "evidence_refs": ["private-ref"], "limitation": "not available in this capture"},
                {"finding_id": "unknown-one", "evidence_state": "unknown", "subject": "private-secret", "statement": "must not leave the report"},
            ],
            "password": "must-not-leak",
        },
        separators=(",", ":"),
    ).encode()


def test_xray_is_content_addressed_redacted_and_keeps_evidence_states_separate(tmp_path) -> None:
    repository, store = _repository(tmp_path)
    source_digest = _register(repository, store, _xray_source())
    service = XrayService(repository, store, personal_project_id="personal")

    report = service.create_report(
        {"source_artifact_digest": source_digest, "source_kind": "repository"},
        project_id=None,
    )

    validated = XRayReport.model_validate(report)
    assert validated.report_digest == validated.report_artifact_digest
    assert {item.status for item in validated.detected_mechanisms} >= {
        "declared", "observed", "inferred", "verified", "unsupported", "unknown"
    }
    assert all(
        item.evidence_refs == [f"artifact:sha256:{source_digest}"]
        for item in validated.detected_mechanisms
        if item.status != "unknown"
    )
    assert next(item for item in validated.detected_mechanisms if item.status == "unknown").evidence_refs == []
    assert "must-not-leak" not in str(report)
    assert "private-secret" not in str(report)
    assert "private-ref" not in str(report)
    persisted = store.get_bytes(report["report_artifact_digest"].removeprefix("sha256:"))
    assert b"must-not-leak" not in persisted
    assert b"private-secret" not in persisted

    replay = service.create_report(
        {"source_artifact_digest": f"sha256:{source_digest}", "source_kind": "repository"},
        project_id=None,
    )
    assert replay["report_digest"] == report["report_digest"]
    assert replay["idempotent_replay"] is True
    assert report["execution_started"] is False
    assert report["network_requested"] is False


@pytest.mark.parametrize(
    "source_kind",
    ["repository", "acp", "cli", "sdk", "otel_bundle", "recorded_run"],
)
def test_xray_accepts_only_declared_static_source_kinds(source_kind: str) -> None:
    request = XRayRequest.model_validate(
        {"source_artifact_digest": "a" * 64, "source_kind": source_kind}
    )
    assert request.source_kind == source_kind
    with pytest.raises(Exception):
        XRayRequest.model_validate(
            {
                "source_artifact_digest": "a" * 64,
                "source_kind": source_kind,
                "source_text": "inline execution material is forbidden",
            }
        )


def test_xray_holds_before_reading_an_oversized_captured_artifact(tmp_path) -> None:
    repository, store = _repository(tmp_path)
    source_digest = _register(repository, store, b"x" * 1_000_001)
    service = XrayService(repository, store, personal_project_id="personal")
    with pytest.raises(XrayError) as held:
        service.create_report(
            {"source_artifact_digest": source_digest, "source_kind": "repository"},
            project_id=None,
        )
    assert held.value.code == "xray_source_too_large"


def _observatory_service(tmp_path) -> tuple[ObservatoryService, XrayService, ArenaRepository, str]:
    repository, store = _repository(tmp_path)
    source_digest = _register(repository, store, _xray_source())
    pack_digest = _register(repository, store, b"synthetic-pack")
    with repository.transaction() as conn:
        conn.execute(
            insert(study_packs).values(
                id="pack-one",
                project_id="personal",
                pack_key="pack",
                version="1.0.0",
                content_digest=pack_digest,
            )
        )
        conn.execute(
            insert(experiments).values(
                id="experiment-one",
                project_id="personal",
                study_pack_id="pack-one",
                name="one",
                protocol_version="1",
                definition={},
            )
        )
        conn.execute(
            insert(executions).values(
                id="execution-one",
                experiment_id="experiment-one",
                status="completed",
                parameters={},
            )
        )
        conn.execute(
            insert(episodes).values(
                id="episode-one", execution_id="execution-one", ordinal=0, metadata_json={}
            )
        )
        conn.execute(
            insert(attempts).values(
                id="attempt-one",
                episode_id="episode-one",
                ordinal=0,
                status="completed",
                request_metadata={},
                result_metadata={"trace_complete": True},
            )
        )
    for event in (
        "factor_declared",
        "factor_assigned",
        "factor_available",
        "factor_triggered",
        "factor_applied",
        "factor_activated",
        "factor_observed",
        "downstream_pathway_detected",
    ):
        repository.append_attempt_event("attempt-one", event, {"api_key": "must-not-leak"})
    return (
        ObservatoryService(repository, store, personal_project_id="personal"),
        XrayService(repository, store, personal_project_id="personal"),
        repository,
        source_digest,
    )


def test_observatory_is_redacted_unknown_aware_and_only_reports_treatment_when_supported(tmp_path) -> None:
    observatory, xray, _, source_digest = _observatory_service(tmp_path)
    xray_report = xray.create_report(
        {"source_artifact_digest": source_digest, "source_kind": "recorded_run"},
        project_id=None,
    )

    report = observatory.create_report(
        {
            "attempt_ids": ["attempt-one"],
            "xray_analysis_digest": xray_report["report_digest"],
            "source_artifact_digest": source_digest,
            "diagnostic_partial_mode": False,
        },
        project_id=None,
    )

    validated = ObservatoryReport.model_validate(report)
    assert validated.source_artifact_digest == f"sha256:{source_digest}"
    assert validated.xray_analysis_digest == xray_report["report_digest"]
    assert validated.fidelity_ladder == [
        "declared", "assigned", "available", "triggered", "applied", "activated", "observed", "downstream_pathway_detected"
    ]
    assert all(stage.status == "observed" for stage in validated.intervention_fidelity)
    assert {
        item["check"] for item in validated.loop_microscope
    } >= {"repeated_state_loops", "deadlock_livelock", "unbounded_delegation"}
    assert {metric["metric_id"] for metric in validated.context_ledger["metrics"]} >= {
        "useful_context_density", "context_cost_per_success"
    }
    conditional = {
        metric.metric_id: metric
        for metric in validated.metrics
        if metric.metric_id in {
            "intention_to_treat", "opportunity", "activation", "fidelity_failure", "treatment_on_the_treated"
        }
    }
    assert set(conditional) == {
        "intention_to_treat", "opportunity", "activation", "fidelity_failure", "treatment_on_the_treated"
    }
    assert all(metric.value is None for metric in conditional.values())
    assert "must-not-leak" not in str(report)
    assert observatory.create_report(
        {
            "attempt_ids": ["attempt-one"],
            "xray_analysis_digest": xray_report["report_digest"],
            "source_artifact_digest": source_digest,
            "diagnostic_partial_mode": False,
        },
        project_id=None,
    )["idempotent_replay"] is True


def test_observatory_rejects_partial_mode_and_missing_custody_source(tmp_path) -> None:
    observatory, _, _, _ = _observatory_service(tmp_path)
    with pytest.raises(Exception):
        ObservatoryRequest.model_validate(
            {"attempt_ids": ["attempt-one"], "diagnostic_partial_mode": True}
        )
    with pytest.raises(ObservatoryError) as held:
        observatory.create_report(
            {
                "attempt_ids": ["attempt-one"],
                "source_artifact_digest": "b" * 64,
                "diagnostic_partial_mode": False,
            },
            project_id=None,
        )
    assert held.value.code == "observatory_source_not_found"


def test_observatory_requires_an_observed_edge_for_downstream_pathway_detection() -> None:
    report = ObservatoryService._analysis(
        [{"attempt_id": "attempt-one", "events": [{"event_type": "downstream_pathway_detected"}]}],
        xray_analysis_digest=None,
        source_artifact_digest=None,
    )
    downstream = next(
        stage
        for stage in report["intervention_fidelity"]
        if stage["stage"] == "downstream_pathway_detected"
    )
    assert downstream["status"] == "unknown"
