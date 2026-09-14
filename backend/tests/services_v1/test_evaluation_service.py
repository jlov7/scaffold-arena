from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from adapters_v1 import AttemptInput
from artifacts_v1 import LocalArtifactStore
from evaluation_v1 import (
    EvaluationWorker,
    GraderInstallation,
    QualitativeGrader,
    TrustedGraderRegistry,
)
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.jobs import (
    LEASE_RECLAIM_BACKOFF_BASE_SECONDS,
    LEASE_RECLAIM_GRACE_SECONDS,
    JobLeaseRepository,
)
from persistence_v1.schema import attempts, evaluations, executions, jobs
from protocol_v1 import AttemptEnvelope, GraderSpec, ScenarioSpec, TraceEvent
from protocol_v1.canonical import canonical_json
from services_v1 import (
    DurableEvaluationService,
    EvaluationError,
    ExecutionService,
    ProtocolRegistryService,
)
from tests.services_v1.test_execution_service import (
    ForbiddenAdapterRegistry,
    experiment_payload,
    pack_payload,
    provenance,
)


class _ObservedJudge(QualitativeGrader):
    def __init__(self, grader_id: str, version: str, digest: str) -> None:
        self.grader_id = grader_id
        self.version = version
        self.digest = digest


def _captured_incomplete_attempt(
    tmp_path, *, bind_output: bool, include_qualitative: bool = False, budget_limit_usd: float = 0.0,
) -> tuple[DurableEvaluationService, ArenaRepository, str]:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    store = LocalArtifactStore(tmp_path / "artifacts")
    protocol = ProtocolRegistryService(repository, store, personal_project_id="personal")
    pack = pack_payload()
    grader_config = {"forbidden_tokens": ["forbidden"]}
    pack["graders"] = [{
        "grader_id": "safe-output", "version": "1", "implementation": "forbidden_token",
        "kind": "deterministic", "config": grader_config,
        "digest": GraderSpec.digest_for(
            grader_id="safe-output", version="1", implementation="forbidden_token",
            kind="deterministic", config=grader_config,
        ),
    }]
    pack["scenarios"][0]["deterministic_metrics"] = [
        {"metric_id": "metric-one", "weight": 0.7 if include_qualitative else 1.0, "oracle": "safe-output"},
    ]
    grader_registry = TrustedGraderRegistry()
    if include_qualitative:
        judge_config: dict[str, str] = {}
        judge_digest = GraderSpec.digest_for(
            grader_id="observed-judge", version="1", implementation="installed_plugin",
            kind="qualitative", config=judge_config,
        )
        pack["graders"].append({
            "grader_id": "observed-judge", "version": "1", "implementation": "installed_plugin",
            "kind": "qualitative", "config": judge_config, "metric_id": "judge", "weight": 0.3,
            "digest": judge_digest,
        })
        grader_registry.install(
            _ObservedJudge("observed-judge", "1", judge_digest),
            GraderInstallation(grader_id="observed-judge", version="1", digest=judge_digest),
        )
    protocol.import_pack(json.dumps(pack).encode(), "application/json", project_id="personal")
    experiment = experiment_payload()
    experiment["budgets"]["max_cost_usd"] = budget_limit_usd
    experiment["aggregate_budget"]["max_total_cost_usd"] = budget_limit_usd
    protocol.create_experiment(experiment, project_id="personal")
    protocol.freeze("experiment-one", project_id="personal")
    ExecutionService(
        repository, store, personal_project_id="personal", adapter_registry=ForbiddenAdapterRegistry(),
    ).create_execution("experiment-one", provenance(), project_id="personal", request_key="evaluation-test")["execution_id"]
    with repository.engine.connect() as conn:
        row = conn.execute(select(attempts).where(attempts.c.id.is_not(None))).mappings().one()
    attempt_id = str(row["id"])
    queued = AttemptEnvelope.model_validate_json(canonical_json(row["request_metadata"]["envelope"]))
    scenario = ScenarioSpec(
        scenario_id="scenario-one", title="Scenario", task_family="extract", prompt="Synthetic prompt.",
    )
    input_bytes = canonical_json(AttemptInput.bind(scenario, queued).model_dump(mode="json"))
    now = datetime.now(UTC)
    trace = TraceEvent(
        trace_id="trace-one", episode_id=queued.episode_id, attempt_id=attempt_id,
        sequence=0, actor="model", event_type="response", timestamp=now,
        monotonic_time=0.0, payload={"observed": True}, payload_hash="a" * 64,
    )
    input_digest = _persist(repository, store, input_bytes, "application/json")
    trace_digest = _persist(
        repository, store, canonical_json([trace.model_dump(mode="json")]), "application/json",
    )
    response_hash = None
    output_digest = None
    if bind_output:
        response_hash = _persist(repository, store, b"answer", "text/plain; charset=utf-8")
        output_digest = response_hash
    terminal = queued.model_copy(update={
        "status": "incomplete", "started_at": now,
        "completed_at": now + timedelta(seconds=1), "response_hash": response_hash,
    })
    with repository.transaction() as conn:
        conn.execute(update(attempts).where(attempts.c.id == attempt_id).values(
            status="incomplete",
            result_metadata={
                "captured_adapter_terminal": True,
                "terminal_outcome": "incomplete",
                "terminal_envelope": terminal.model_dump(mode="json"),
                "input_artifact_digest": input_digest,
                "output_artifact_digest": output_digest,
                "trace_artifact_digest": trace_digest,
                "trace_complete": True,
                "response_hash": response_hash,
                "cost_status": "unknown",
                "cost_usd": None,
                "limitations": ["provider_identity_evidence_incomplete"],
            },
        ))
    return DurableEvaluationService(repository, store, grader_registry), repository, attempt_id


def _persist(repository: ArenaRepository, store: LocalArtifactStore, content: bytes, media_type: str) -> str:
    digest = store.put_bytes(content, media_type=media_type)
    repository.register_artifact(
        digest, size_bytes=len(content), storage_uri=store.uri_for(digest), media_type=media_type,
    )
    return digest


def _set_reconciled_terminal_cost(
    repository: ArenaRepository, attempt_id: str, *, cost_usd: float | None,
) -> None:
    with repository.transaction() as conn:
        row = conn.execute(select(attempts).where(attempts.c.id == attempt_id)).mappings().one()
        result = dict(row["result_metadata"])
        result["cost_status"] = "reconciled" if cost_usd is not None else "unknown"
        result["cost_usd"] = cost_usd
        conn.execute(
            update(attempts).where(attempts.c.id == attempt_id).values(
                result_metadata=result,
            )
        )


def test_evaluates_bound_incomplete_output_with_explicit_claim_exclusions(tmp_path) -> None:
    service, repository, attempt_id = _captured_incomplete_attempt(tmp_path, bind_output=True)
    result = service.evaluate("personal", attempt_id)
    assert result["record"]["outcome"]["deterministic"] == {"metric-one": 1.0}
    with repository.engine.connect() as conn:
        evaluation = conn.execute(select(evaluations).where(evaluations.c.attempt_id == attempt_id)).mappings().one()
    assert evaluation["output_artifact_digest"] is not None
    assert "provider_cost_identity_claims_hold_for_incomplete_adapter_evidence" in evaluation["result"]["exclusions"]
    assert "quality_scored_from_bound_output_only" in evaluation["result"]["claim_limitations"]


def test_incomplete_attempt_without_output_is_not_quality_scored(tmp_path) -> None:
    service, repository, attempt_id = _captured_incomplete_attempt(tmp_path, bind_output=False)
    result = service.evaluate("personal", attempt_id)
    assert result["record"]["outcome"]["deterministic"] == {}
    with repository.engine.connect() as conn:
        evaluation = conn.execute(select(evaluations).where(evaluations.c.attempt_id == attempt_id)).mappings().one()
    assert evaluation["output_artifact_digest"] is None
    assert evaluation["result"]["adapter_terminal_label"] == "adapter_terminal:incomplete"


def test_stale_evaluator_same_owner_cannot_publish_after_reclaim(tmp_path) -> None:
    service, repository, attempt_id = _captured_incomplete_attempt(tmp_path, bind_output=True)
    leases = JobLeaseRepository(repository)
    job = service.enqueue("personal", attempt_id)
    started = datetime.now(UTC) + timedelta(minutes=1)
    stale = leases.claim("shared-evaluator", lease_seconds=1, now=started, kind="evaluation")
    assert stale is not None and stale.id == job
    reclaim_at = stale.expires_at + timedelta(seconds=LEASE_RECLAIM_GRACE_SECONDS)
    assert leases.reclaim_expired(now=reclaim_at) == 1
    fresh = leases.claim(
        "shared-evaluator",
        lease_seconds=30,
        now=reclaim_at + timedelta(seconds=LEASE_RECLAIM_BACKOFF_BASE_SECONDS),
        kind="evaluation",
    )
    assert fresh is not None and fresh.token != stale.token
    with pytest.raises(EvaluationError) as error:
        service.evaluate("personal", attempt_id, lease=stale)
    assert error.value.code == "evaluation_lease_lost"
    with repository.engine.connect() as conn:
        assert conn.execute(select(evaluations.c.id).where(evaluations.c.attempt_id == attempt_id)).scalar_one_or_none() is None
        current = conn.execute(select(jobs).where(jobs.c.id == job)).mappings().one()
    assert current["status"] == "running"
    assert current["lease_token"] == fresh.token


def test_evaluator_heartbeats_while_synchronous_evaluation_runs(tmp_path, monkeypatch) -> None:
    service, repository, attempt_id = _captured_incomplete_attempt(tmp_path, bind_output=True)
    service.enqueue("personal", attempt_id)
    worker = EvaluationWorker(repository, service.artifact_store, TrustedGraderRegistry())
    heartbeats = 0
    original_heartbeat = worker.jobs.heartbeat

    def heartbeat(*args, **kwargs):
        nonlocal heartbeats
        heartbeats += 1
        return original_heartbeat(*args, **kwargs)

    class SlowService:
        def evaluate(self, project_id: str, observed_attempt_id: str, *, lease) -> dict[str, object]:
            assert project_id == "personal"
            assert observed_attempt_id == attempt_id
            assert lease.token
            time.sleep(0.35)
            return {}

    monkeypatch.setattr(worker.jobs, "heartbeat", heartbeat)
    worker.service = SlowService()
    result = worker.run_once("evaluator", lease_seconds=0.2)
    assert result is not None and result.status == "completed"
    assert heartbeats >= 1


@pytest.mark.parametrize(
    ("cost_usd", "budget_limit_usd", "expected"),
    [
        (0.25, 1.0, "within_budget"),
        (1.0, 1.0, "within_budget"),
        (1.01, 1.0, "over_budget"),
        (None, 1.0, "unknown"),
    ],
)
def test_terminal_failure_cost_status_requires_reconciled_persisted_budget(
    tmp_path, cost_usd: float | None, budget_limit_usd: float, expected: str,
) -> None:
    service, repository, attempt_id = _captured_incomplete_attempt(
        tmp_path, bind_output=False, budget_limit_usd=budget_limit_usd,
    )
    _set_reconciled_terminal_cost(
        repository, attempt_id, cost_usd=cost_usd,
    )
    result = service.evaluate("personal", attempt_id)
    assert result["record"]["outcome"]["cost_status"] == expected


def test_reconciled_cost_without_execution_budget_envelope_remains_unknown(tmp_path) -> None:
    service, repository, attempt_id = _captured_incomplete_attempt(
        tmp_path, bind_output=False, budget_limit_usd=1.0,
    )
    _set_reconciled_terminal_cost(repository, attempt_id, cost_usd=0.25)
    with repository.transaction() as conn:
        conn.execute(update(executions).values(parameters={}))
    result = service.evaluate("personal", attempt_id)
    assert result["record"]["outcome"]["cost_status"] == "unknown"


def test_durable_evaluator_persists_uncalibrated_qualitative_plan_for_review(tmp_path) -> None:
    service, repository, attempt_id = _captured_incomplete_attempt(
        tmp_path, bind_output=True, include_qualitative=True,
    )
    service.evaluate("personal", attempt_id)
    with repository.engine.connect() as conn:
        evaluation = conn.execute(
            select(evaluations).where(evaluations.c.attempt_id == attempt_id)
        ).mappings().one()
    assert evaluation["grader_plan"]["human_calibration_receipt"] is None
    assert [binding["kind"] for binding in evaluation["grader_plan"]["bindings"]] == [
        "deterministic", "qualitative",
    ]
    assert any("no explicit observed result" in item for item in evaluation["result"]["exclusions"])
