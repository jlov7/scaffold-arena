from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from adapters_v1 import (
    AdapterRegistry,
    ArtifactRef,
    ProviderUsage,
    RecordedAdapter,
    ResultBundle,
)
from artifacts_v1 import LocalArtifactStore
from evaluation_v1 import EvaluationWorker, TrustedGraderRegistry
from execution_v1 import DurableWorker
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.schema import attempts, episodes, evaluations, executions, jobs
from protocol_v1 import GraderSpec, TraceEvent
from protocol_v1.canonical import canonical_json, sha256_bytes
from services_v1 import (
    AnalysisService,
    DecisionService,
    EvidenceError,
    EvidenceService,
    ExecutionService,
    ProtocolRegistryService,
)
from tests.services_v1.test_analysis_service import _configuration
from tests.services_v1.test_execution_service import (
    ForbiddenAdapterRegistry,
    experiment_payload,
    pack_payload,
    provenance,
)


def test_frozen_fixture_execution_flows_to_custodied_decision_brief(
    tmp_path: Path,
) -> None:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    store = LocalArtifactStore(tmp_path / "artifacts")
    protocol = ProtocolRegistryService(repository, store, personal_project_id="personal")

    analysis_config = _configuration()
    pack = pack_payload()
    grader_config = {"expected": {"response": "fixture"}}
    grader_digest = GraderSpec.digest_for(
        grader_id="fixture-exact",
        version="1",
        implementation="exact_field",
        kind="deterministic",
        config=grader_config,
    )
    pack["graders"] = [
        {
            "grader_id": "fixture-exact",
            "version": "1",
            "implementation": "exact_field",
            "kind": "deterministic",
            "config": grader_config,
            "digest": grader_digest,
        }
    ]
    pack["scenarios"][0]["deterministic_metrics"] = [
        {"metric_id": "fixture", "weight": 1.0, "oracle": "fixture-exact"}
    ]
    pack["harnesses"][0]["timeout_seconds"] = 1
    protocol.import_pack(
        json.dumps(pack).encode(), "application/json", project_id="personal"
    )
    protocol.create_experiment(
        experiment_payload()
        | {"extensions": {"org.scaffold-arena.analysis-v1": analysis_config}},
        project_id="personal",
    )
    frozen = protocol.freeze("experiment-one", project_id="personal")
    assert frozen["frozen"] is True

    execution = ExecutionService(
        repository,
        store,
        personal_project_id="personal",
        adapter_registry=ForbiddenAdapterRegistry(),
    ).create_execution(
        "experiment-one",
        provenance(),
        project_id="personal",
        request_key="full-chain-fixture",
    )
    execution_id = execution["execution_id"]
    with repository.engine.connect() as connection:
        attempt_id, episode_id = connection.execute(
            select(attempts.c.id, episodes.c.id).join(
                episodes, attempts.c.episode_id == episodes.c.id
            )
        ).one()

    output = canonical_json({"response": "fixture"})
    output_digest = sha256_bytes(output)
    adapter = RecordedAdapter(
        adapter_id="recorded-fixture",
        adapter_digest="2" * 64,
        results={
            attempt_id: ResultBundle(
                attempt_id=attempt_id,
                terminal_outcome="completed",
                completed_at=datetime.now(UTC) + timedelta(seconds=1),
                response_hash=output_digest,
                response_artifact_id="response",
                artifacts=(
                    ArtifactRef(
                        artifact_id="response",
                        media_type="application/json",
                        sha256=output_digest,
                        content=output,
                    ),
                ),
                usage=ProviderUsage(
                    evidence_source="fixture_recorded",
                    total_tokens=1,
                    context_tokens=1,
                    tool_calls=0,
                ),
            )
        },
        events={
            attempt_id: (
                TraceEvent(
                    trace_id="fixture-trace",
                    episode_id=episode_id,
                    attempt_id=attempt_id,
                    sequence=0,
                    actor="model",
                    event_type="response",
                    timestamp=datetime.now(UTC),
                    monotonic_time=0,
                    payload={"fixture": True},
                    payload_hash="a" * 64,
                ),
            )
        },
    )
    adapters = AdapterRegistry()
    asyncio.run(adapters.install_trusted(adapter, "2" * 64))

    attempt_worker = DurableWorker(repository, adapters, store)
    attempt_result = asyncio.run(attempt_worker.run_once("fixture-attempt-worker"))
    assert attempt_result is not None and attempt_result.status == "completed"
    evaluation_result = EvaluationWorker(
        repository, store, TrustedGraderRegistry()
    ).run_once("fixture-evaluator-worker")
    assert evaluation_result is not None and evaluation_result.status == "completed"

    with repository.engine.connect() as connection:
        attempt = connection.execute(
            select(attempts).where(attempts.c.id == attempt_id)
        ).mappings().one()
        evaluation = connection.execute(
            select(evaluations).where(evaluations.c.attempt_id == attempt_id)
        ).mappings().one()
        execution_row = connection.execute(
            select(executions).where(executions.c.id == execution_id)
        ).mappings().one()
        job_statuses = dict(
            connection.execute(
                select(jobs.c.kind, jobs.c.status).where(
                    jobs.c.execution_id == execution_id
                )
            ).all()
        )
    assert attempt["status"] == "completed"
    assert evaluation["evaluator"] == "arena-evaluator"
    assert "outcome" not in evaluation["result"]
    assert evaluation["result"]["record"]["outcome"]["mission_success"] == 1.0
    assert evaluation["result"]["evaluator_independent"] is True
    assert job_statuses == {"attempt": "completed", "evaluation": "completed"}
    assert execution_row["status"] == "completed"
    assert evaluation["input_artifact_digest"] == attempt["result_metadata"][
        "input_artifact_digest"
    ]
    assert evaluation["output_artifact_digest"] == attempt["result_metadata"][
        "output_artifact_digest"
    ]
    assert evaluation["trace_artifact_digest"] == attempt["result_metadata"][
        "trace_artifact_digest"
    ]

    analysis = AnalysisService(repository, store, personal_project_id="personal")
    analysis_result = analysis.analyze(
        {
            "experiment_id": "experiment-one",
            "execution_id": execution_id,
            "analysis_config": analysis_config,
        },
        project_id="personal",
    )
    assert analysis_result["integrity_not_truth"] is True
    report = repository.get_analysis_report("personal", execution_id)
    assert report is not None

    evidence = EvidenceService(repository, store, personal_project_id="personal")
    receipt = evidence.derive_execution_receipt(
        {"execution_id": execution_id, "request_key": "full-chain-fixture"},
        project_id="personal",
    )
    assert receipt["admission_workflow"] == "derived_execution"
    assert receipt["evidence_type"] == "derived_fixture"
    assert receipt["evidence_class"] == "fixture"
    assert "fixture" in receipt["claim_ceiling"]
    assert evidence.verify_receipt(receipt["receipt_id"], project_id="personal")[
        "verified"
    ] is True

    decision = DecisionService(repository, store, personal_project_id="personal").create(
        {
            "analysis_report_id": report["id"],
            "risk_constraints": {
                "severe_failure_disposition": "HOLD",
                "require_zero_exclusions": True,
                "require_estimated_effect_for_effect_claims": True,
                "maximum_claim_ceiling": "independent",
            },
            "proposed_claims": [
                {
                    "claim_id": "fixture-chain-observation",
                    "statement": "The fixture execution chain was durably recorded.",
                    "kind": "fixture_observation",
                    "linked_receipt_ids": [receipt["receipt_id"]],
                }
            ],
        },
        project_id="personal",
    )
    assert decision["claim_ceiling"] == "fixture_only"

    for digest in (
        evaluation["result_artifact_digest"],
        report["artifact_digest"],
        decision["brief_ref"].removeprefix("sha256:"),
        decision["ledger_ref"].removeprefix("sha256:"),
    ):
        assert sha256_bytes(store.get_bytes(digest)) == digest

    binding, rows, prices = repository.derived_execution_evidence_source(
        "personal", execution_id
    )
    assert binding is not None
    ambiguous = deepcopy(rows)
    attempt_job = next(job for job in ambiguous[0]["jobs"] if job["kind"] == "attempt")
    ambiguous[0]["jobs"].append(dict(attempt_job))
    with pytest.raises(EvidenceError, match="exactly one attempt and one evaluation job"):
        evidence._derive_manifest("personal", binding, ambiguous, prices)
