from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path

from sqlalchemy import select

from adapters_v1.offline_fixture import (
    OFFLINE_DEMO_ADAPTER_DIGEST,
    OFFLINE_DEMO_ADAPTER_ID,
    OfflineDemoFixtureStateOracle,
)
from artifacts_v1 import LocalArtifactStore
from evaluation_v1 import EvaluationWorker, TrustedGraderRegistry
from execution_v1 import DurableWorker
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.schema import attempts, episodes, evaluations, executions, jobs
from protocol_v1 import load_study_pack
from services_v1 import (
    AnalysisService,
    EvidenceService,
    ExecutionService,
    ProtocolRegistryService,
    build_adapter_registry_from_config,
)

PACK_ROOT = Path(__file__).resolve().parents[3] / "study_packs" / "offline-demo-v1"


def _pack_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path in sorted(PACK_ROOT.rglob("*")):
            if path.is_file():
                archive.writestr(path.relative_to(PACK_ROOT).as_posix(), path.read_bytes())
    return output.getvalue()


def _provenance() -> dict[str, object]:
    return {
        "code_revision": "offline-demo-fixture-test",
        "code_hash": "a" * 64,
        "runtime_image": "offline-fixture-runtime",
        "runtime_image_hash": "b" * 64,
        "environment_hash": "c" * 64,
        "prompt_hash": "d" * 64,
        "context_hash": "e" * 64,
        "tool_hash": "f" * 64,
        "source_refs": [{"source_uri": "synthetic://offline-demo", "content_hash": "0" * 64}],
        "captured_at": "2026-08-14T00:00:00Z",
    }


def test_bundled_offline_demo_runs_all_80_attempts_through_durable_fixture_chain(tmp_path: Path) -> None:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    store = LocalArtifactStore(tmp_path / "artifacts")
    adapters = asyncio.run(build_adapter_registry_from_config({
        "format": "scaffold-arena-adapter-runtime-v1",
        "adapters": [{"kind": "bundled_offline_demo_fixture"}],
    }))
    assert adapters.capabilities(OFFLINE_DEMO_ADAPTER_ID, OFFLINE_DEMO_ADAPTER_DIGEST).claim_eligibility == "fixture_only"

    protocol = ProtocolRegistryService(repository, store, personal_project_id="personal", adapter_registry=adapters)
    imported = protocol.import_pack(_pack_zip(), "application/zip", project_id="personal")
    pack = load_study_pack(PACK_ROOT)
    experiment = pack.experiments[0]
    protocol.create_experiment(experiment.model_dump(mode="json"), project_id="personal")
    protocol.freeze(experiment.experiment_id, project_id="personal")
    preflight = protocol.preflight(experiment.experiment_id, project_id="personal")
    assert preflight["verdict"] == "PASS"
    assert preflight["expected_attempts"] == 80
    assert preflight["harnesses"][0]["trusted_adapter_present"] is True
    assert imported["study_pack_id"] == "offline-demo-v1"

    execution_service = ExecutionService(repository, store, personal_project_id="personal", adapter_registry=adapters)
    execution = execution_service.create_execution(
        experiment.experiment_id,
        _provenance(),
        project_id="personal",
        request_key="offline-demo-fixture-chain",
    )
    execution_id = execution["execution_id"]
    assert execution["expected_attempts"] == 80

    worker = DurableWorker(repository, adapters, store, state_oracle=OfflineDemoFixtureStateOracle())
    completed_attempt_jobs = 0
    while result := asyncio.run(worker.run_once("offline-demo-attempt-worker")):
        assert result.status == "completed", result.detail
        completed_attempt_jobs += 1
    assert completed_attempt_jobs == 80

    evaluator = EvaluationWorker(repository, store, TrustedGraderRegistry())
    completed_evaluation_jobs = 0
    while result := evaluator.run_once("offline-demo-evaluator-worker"):
        assert result.status == "completed"
        completed_evaluation_jobs += 1
    assert completed_evaluation_jobs == 80

    with repository.engine.connect() as connection:
        attempt_rows = connection.execute(select(
            attempts.c.id,
            attempts.c.status,
            attempts.c.result_metadata,
            episodes.c.scenario_id,
        ).join(episodes, episodes.c.id == attempts.c.episode_id).order_by(attempts.c.id)).mappings().all()
        evaluation_rows = connection.execute(select(
            evaluations.c.attempt_id,
            evaluations.c.result,
        )).mappings().all()
        execution_row = connection.execute(select(executions.c.status).where(executions.c.id == execution_id)).one()
        job_counts = connection.execute(select(jobs.c.kind, jobs.c.status).where(jobs.c.execution_id == execution_id)).all()

    assert len(attempt_rows) == 80
    assert len(evaluation_rows) == 80
    assert execution_row.status == "completed"
    assert {kind for kind, _status in job_counts} == {"attempt", "evaluation"}
    assert all(status == "completed" for _kind, status in job_counts)
    for row in attempt_rows:
        result_metadata = dict(row["result_metadata"])
        assert row["status"] == "completed"
        assert result_metadata["trace_complete"] is True
        assert result_metadata["manipulation_pass"] is True
        assert result_metadata["cost_status"] == "unknown"
        assert result_metadata["usage"] == {
            "evidence_source": "fixture_recorded",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "context_tokens": 0,
            "tool_calls": 0,
            "cached_input_tokens": None,
            "service_tier": None,
            "billing_profile": None,
            "tool_billing_usd": None,
            "actual_cost_usd": 0.0,
            "provider_usage_digest": "c334ec1911a39d529a00678e58ba734769fb41585588d3277cd8d76998b71952",
            "observed_provider_version": None,
            "observed_endpoint_digest": None,
            "operator_attested_runtime_revision": None,
        }
        trace = json.loads(store.get_bytes(result_metadata["trace_artifact_digest"]))
        assert trace[0]["attempt_id"] == row["id"]
        assert trace[0]["payload"]["event"] == "bundled_fixture_binding"
        assert trace[0]["payload"]["truth_table_digest"] == "92587ad86a7623b55b57fe1efcd5b4d84da907dd729e30be0ee719a7886c738d"
        assert {event["payload"].get("factor_id") for event in trace if event["payload"].get("event") == "factor_fidelity"} == {
            "planning", "verification", "recovery", "memory",
        }
        assert any(event["payload"].get("event") == "bundled_fixture_state" for event in trace)

    outcomes_by_scenario: dict[str, list[dict[str, object]]] = {}
    evaluation_by_attempt = {str(row["attempt_id"]): dict(row["result"]) for row in evaluation_rows}
    for row in attempt_rows:
        outcomes_by_scenario.setdefault(str(row["scenario_id"]), []).append(evaluation_by_attempt[str(row["id"])] ["record"]["outcome"])
    assert all(item["mission_success"] == 1.0 for item in outcomes_by_scenario["positive-control"])
    assert all(item["mission_success"] == 0.0 for item in outcomes_by_scenario["negative-control"])
    assert all(item["mission_success"] == 0.0 for item in outcomes_by_scenario["anti-cheat-control"])
    assert all(item["severe_failures"] == ["fixture-claim-ceiling-breach"] for item in outcomes_by_scenario["anti-cheat-control"])
    assert {item["mission_success"] for item in outcomes_by_scenario["candidate-clean"]} == {0.0, 1.0}
    assert {item["mission_success"] for item in outcomes_by_scenario["candidate-stress"]} == {0.0, 1.0}

    analysis_config = dict(experiment.extensions["org.scaffold-arena.analysis-v1"])
    analysis = AnalysisService(repository, store, personal_project_id="personal").analyze({
        "experiment_id": experiment.experiment_id,
        "execution_id": execution_id,
        "analysis_config": analysis_config,
    }, project_id="personal")
    assert analysis["integrity_not_truth"] is True
    assert analysis["verdict"] == "HOLD"
    report = AnalysisService(repository, store, personal_project_id="personal").report(
        analysis["report_digest"], project_id="personal",
    )["report"]
    assert len(report["main_effects"]) == 4
    assert report["main_effects"][0]["status"] == "ESTIMATED"
    assert report["main_effects"][0]["estimate"] > 0.0
    assert len(report["secondary_interactions"]) == 1
    assert report["secondary_interactions"][0]["status"] == "ESTIMATED"
    assert report["adequacy"]["claim_level"] == "DESCRIPTIVE_ONLY"
    assert report["adequacy"]["mixed_effect_status"] == "NOT_RUN"

    evidence = EvidenceService(repository, store, personal_project_id="personal")
    receipt = evidence.derive_execution_receipt({
        "execution_id": execution_id,
        "request_key": "offline-demo-fixture-receipt",
    }, project_id="personal")
    assert receipt["evidence_type"] == "derived_fixture"
    assert receipt["evidence_class"] == "fixture"
    assert "fixture" in receipt["claim_ceiling"]
    assert evidence.verify_receipt(receipt["receipt_id"], project_id="personal")["verified"] is True
