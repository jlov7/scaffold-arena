from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, select, update

from analysis_v1 import AnalysisInput, build_analysis_report
from artifacts_v1 import LocalArtifactStore
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.schema import (
    analysis_reports,
    attempts,
    episodes,
    evaluations,
    executions,
    jobs,
    usage_ledger,
)
from protocol_v1 import AttemptEnvelope
from protocol_v1.canonical import canonical_json
from services_v1 import (
    AnalysisError,
    AnalysisService,
    ExecutionService,
    ProtocolRegistryService,
)
from tests.services_v1.test_execution_service import (
    ForbiddenAdapterRegistry,
    experiment_payload,
    pack_payload,
    provenance,
)


def _configuration() -> dict:
    return {
        "registered_factors": [],
        "primary_main_effects": [],
        "secondary_interactions": [],
        "gates": {
            "preregistered_design": True,
            "comparison_invariants_pass": True,
            "minimum_manipulation_fidelity": 0.95,
            "minimum_trace_completeness": 0.95,
            "require_evaluator_independence": True,
            "require_held_out_tasks": True,
            "external_fitter_receipt": None,
        },
        "options": {
            "pass_k": 2,
            "bootstrap_resamples": 10,
            "bootstrap_seed": 1,
            "minimum_clusters": 2,
        },
    }


def _service(tmp_path):
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    store = LocalArtifactStore(tmp_path / "artifacts")
    registry = ProtocolRegistryService(
        repository, store, personal_project_id="personal"
    )
    registry.import_pack(
        json.dumps(pack_payload()).encode(),
        "application/json",
        project_id="personal",
    )
    raw_spec = experiment_payload() | {
        "extensions": {"org.scaffold-arena.analysis-v1": _configuration()}
    }
    registry.create_experiment(raw_spec, project_id="personal")
    registry.freeze("experiment-one", project_id="personal")
    execution = ExecutionService(
        repository,
        store,
        personal_project_id="personal",
        adapter_registry=ForbiddenAdapterRegistry(),
    ).create_execution(
        "experiment-one",
        provenance(),
        project_id="personal",
        request_key="analysis-test",
    )["execution_id"]
    with repository.engine.connect() as conn:
        attempt_id = conn.execute(select(attempts.c.id)).scalar_one()
    now = datetime.now(UTC)
    with repository.transaction() as conn:
        queued_envelope = dict(
            conn.execute(
                select(attempts.c.request_metadata).where(attempts.c.id == attempt_id)
            ).scalar_one()["envelope"]
        )
        digests = []
        for body in (b"input", b"output", b"trace"):
            digest = store.put_bytes(body)
            repository.register_artifact(
                digest,
                size_bytes=len(body),
                storage_uri=store.uri_for(digest),
                media_type="application/json",
            )
            digests.append(digest)
        terminal_envelope = AttemptEnvelope.model_validate_json(
            json.dumps(
                queued_envelope
                | {
                    "status": "completed",
                    "started_at": now.isoformat(),
                    "completed_at": (now + timedelta(seconds=1)).isoformat(),
                    "response_hash": digests[1],
                }
            )
        ).model_dump(mode="json")
        conn.execute(
            update(executions)
            .where(executions.c.id == execution)
            .values(status="completed")
        )
        episode_metadata = dict(
            conn.execute(
                select(episodes.c.metadata_json).where(
                    episodes.c.execution_id == execution
                )
            ).scalar_one()
        )
        conn.execute(
            update(episodes)
            .where(episodes.c.execution_id == execution)
            .values(metadata_json={**episode_metadata, "held_out": True})
        )
        conn.execute(
            update(attempts)
            .where(attempts.c.id == attempt_id)
            .values(
                status="completed",
                result_metadata={
                    "input_artifact_digest": digests[0],
                    "output_artifact_digest": digests[1],
                    "trace_artifact_digest": digests[2],
                    "response_hash": digests[1],
                    "terminal_envelope": terminal_envelope,
                    "trace_complete": True,
                    "manipulation_pass": True,
                },
            )
        )
        conn.execute(
            insert(evaluations).values(
                id="evaluation-one",
                attempt_id=attempt_id,
                evaluator="offline",
                score=1.0,
                result={
                    "evaluator_independent": True,
                    "outcome": {
                        "mission_success": 1.0,
                        "auditability": 1.0,
                        "severe_failures": [],
                        "deterministic": {},
                    },
                },
                project_id="personal",
                evaluator_version="1",
                evaluator_digest="a" * 64,
                input_artifact_digest=digests[0],
                output_artifact_digest=digests[1],
                trace_artifact_digest=digests[2],
                result_hash="b" * 64,
            )
        )
        conn.execute(
            update(jobs)
            .where(jobs.c.attempt_id == attempt_id, jobs.c.kind == "attempt")
            .values(status="completed", attempt_count=1)
        )
        conn.execute(
            insert(jobs).values(
                id="evaluation-job-one",
                execution_id=execution,
                attempt_id=attempt_id,
                kind="evaluation",
                status="completed",
                attempt_count=1,
                available_at=now,
                payload={},
            )
        )
    return AnalysisService(repository, store, personal_project_id="personal"), execution


def _replace_terminal_envelope(
    service: AnalysisService, update_fields: dict[str, object]
) -> None:
    with service.repository.transaction() as conn:
        attempt_id = conn.execute(select(attempts.c.id)).scalar_one()
        result = dict(
            conn.execute(select(attempts.c.result_metadata)).scalar_one()
        )
        result["terminal_envelope"] = AttemptEnvelope.model_validate_json(
            json.dumps(dict(result["terminal_envelope"]) | update_fields)
        ).model_dump(mode="json")
        conn.execute(
            update(attempts)
            .where(attempts.c.id == attempt_id)
            .values(result_metadata=result)
        )


def _add_transient_retry(
    service: AnalysisService,
    *,
    first_trace_complete: bool = True,
    reconciled_costs: bool = False,
    precursor_terminal_envelope: bool = False,
) -> str:
    """Turn the fixture attempt into a transient precursor and append its retry."""
    with service.repository.transaction() as conn:
        first_id = conn.execute(select(attempts.c.id)).scalar_one()
        first = dict(
            conn.execute(select(attempts).where(attempts.c.id == first_id)).mappings().one()
        )
        request = dict(first["request_metadata"])
        original = dict(request["envelope"])
        result = dict(first["result_metadata"])
        retry_id = "attempt-retry"
        now = datetime.now(UTC)
        failed_terminal = AttemptEnvelope.model_validate_json(
            json.dumps(
                original
                | {
                    "status": "failed",
                    "started_at": now.isoformat(),
                    "completed_at": (now + timedelta(seconds=2)).isoformat(),
                    "response_hash": None,
                }
            )
        ).model_dump(mode="json")
        result.update(
            {
                "output_artifact_digest": None,
                "response_hash": None,
                "failure_classification": "transient_provider",
                "trace_complete": first_trace_complete,
                "manipulation_pass": True,
            }
        )
        if precursor_terminal_envelope:
            result["terminal_envelope"] = failed_terminal
        else:
            result.pop("terminal_envelope", None)
        conn.execute(
            update(attempts)
            .where(attempts.c.id == first_id)
            .values(status="failed", result_metadata=result)
        )
        retry_queued = AttemptEnvelope.model_validate_json(
            json.dumps(
                original
                | {
                    "attempt_id": retry_id,
                    "ordinal": int(original["ordinal"]) + 1,
                    "request_hash": "c" * 64,
                    "queued_at": (now + timedelta(seconds=3)).isoformat(),
                    "status": "queued",
                    "started_at": None,
                    "completed_at": None,
                    "response_hash": None,
                }
            )
        ).model_dump(mode="json")
        retry_terminal = AttemptEnvelope.model_validate_json(
            json.dumps(
                retry_queued
                | {
                    "status": "completed",
                    "started_at": (now + timedelta(seconds=4)).isoformat(),
                    "completed_at": (now + timedelta(seconds=7)).isoformat(),
                    "response_hash": first["result_metadata"]["output_artifact_digest"],
                }
            )
        ).model_dump(mode="json")
        retry_result = dict(first["result_metadata"])
        retry_result["terminal_envelope"] = retry_terminal
        conn.execute(
            insert(attempts).values(
                id=retry_id,
                episode_id=first["episode_id"],
                ordinal=1,
                status="completed",
                request_metadata={**request, "retry_of_attempt_id": first_id, "envelope": retry_queued},
                result_metadata=retry_result,
            )
        )
        conn.execute(
            update(evaluations)
            .where(evaluations.c.attempt_id == first_id)
            .values(attempt_id=retry_id)
        )
        if reconciled_costs:
            for attempt_id, cost in ((first_id, 0.1), (retry_id, 0.2)):
                conn.execute(
                    insert(usage_ledger).values(
                        id=f"usage-{attempt_id}", execution_id=conn.execute(
                            select(episodes.c.execution_id).where(episodes.c.id == first["episode_id"])
                        ).scalar_one(), attempt_id=attempt_id, model_id="recorded",
                        input_tokens=1, output_tokens=1, total_tokens=2,
                        context_tokens=1, tool_calls=0,
                        cost_status="reconciled", actual_cost_usd=cost, cost_usd=cost,
                        provider_usage_digest=("d" if attempt_id == first_id else "e") * 64,
                        price_catalog_revision="prices-v1",
                    )
                )
    return retry_id


def test_analysis_uses_only_frozen_configuration_and_persisted_evidence(
    tmp_path,
) -> None:
    service, execution_id = _service(tmp_path)
    request = {
        "experiment_id": "experiment-one",
        "execution_id": execution_id,
        "analysis_config": _configuration(),
    }
    first = service.analyze(request, project_id="personal")
    replay = service.analyze(request, project_id="personal")
    assert first["artifact_ref"] == f"sha256:{first['artifact_digest']}"
    assert replay["idempotent_replay"] is True
    with service.repository.engine.connect() as conn:
        assert (
            conn.execute(select(analysis_reports.c.execution_id)).scalar_one()
            == execution_id
        )
    changed = {
        **request,
        "analysis_config": {
            **_configuration(),
            "options": {**_configuration()["options"], "pass_k": 3},
        },
    }
    with pytest.raises(AnalysisError, match="exactly match"):
        service.analyze(changed, project_id="personal")
    forged = {**request, "profiles": []}
    with pytest.raises(AnalysisError, match="Use exactly"):
        service.analyze(forged, project_id="personal")


def test_transient_retry_is_one_episode_record_with_aggregate_evidence(tmp_path) -> None:
    service, execution_id = _service(tmp_path)
    retry_id = _add_transient_retry(
        service, reconciled_costs=True, precursor_terminal_envelope=True
    )
    _execution, rows = service.repository.analysis_execution_rows("personal", "experiment-one", execution_id)
    records = service._attempts("experiment-one", rows)
    assert len(records) == 1
    record = records[0]
    assert record.attempt_id == retry_id
    assert record.constituent_attempt_ids[1] == retry_id
    assert len(record.constituent_attempt_ids) == 2
    assert record.cost_status.value == "reconciled"
    assert record.cost_usd == pytest.approx(0.3)
    assert record.latency_seconds == pytest.approx(5.0)
    assert dict(record.continuous_outcomes) == {
        "infrastructure_retry_count": 1.0,
        "recovered_transient_failure": 1.0,
    }
    report = build_analysis_report(
        AnalysisInput.model_validate_json(
            canonical_json(
                {"experiment_id": "experiment-one", "attempts": records, **_configuration()}
            )
        )
    )
    assert report.profiles[0].pass_at_1.denominator == 1
    assert report.profiles[0].pass_at_1.constituent_attempt_ids == record.constituent_attempt_ids


def test_episode_cost_and_trace_are_conjunctive_across_retries(tmp_path) -> None:
    service, execution_id = _service(tmp_path)
    _add_transient_retry(service, first_trace_complete=False)
    _execution, rows = service.repository.analysis_execution_rows("personal", "experiment-one", execution_id)
    records = service._attempts("experiment-one", rows)
    assert len(records) == 1
    record = records[0]
    assert record.cost_status.value == "unknown"
    assert record.cost_usd is None
    assert record.latency_seconds is None
    assert record.trace_complete is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("nontransient", "non-transient"),
        ("branch", "ordinal predecessor"),
    ],
)
def test_analysis_holds_invalid_retry_chain(tmp_path, mutation: str, message: str) -> None:
    service, execution_id = _service(tmp_path)
    retry_id = _add_transient_retry(service)
    with service.repository.transaction() as conn:
        first_id = conn.execute(
            select(attempts.c.id).where(attempts.c.id != retry_id)
        ).scalar_one()
        if mutation == "nontransient":
            result = dict(conn.execute(select(attempts.c.result_metadata).where(attempts.c.id == first_id)).scalar_one())
            result["failure_classification"] = "permanent_protocol"
            conn.execute(update(attempts).where(attempts.c.id == first_id).values(result_metadata=result))
        else:
            request = dict(conn.execute(select(attempts.c.request_metadata).where(attempts.c.id == retry_id)).scalar_one())
            request["retry_of_attempt_id"] = "not-the-predecessor"
            conn.execute(update(attempts).where(attempts.c.id == retry_id).values(request_metadata=request))
    _execution, rows = service.repository.analysis_execution_rows("personal", "experiment-one", execution_id)
    with pytest.raises(AnalysisError, match=message):
        service._attempts("experiment-one", rows)


@pytest.mark.parametrize("family", ("primary_main_effects", "secondary_interactions"))
def test_analysis_rejects_caller_supplied_effect_p_values(tmp_path, family: str) -> None:
    service, execution_id = _service(tmp_path)
    config = _configuration()
    config[family] = [{"raw_p_value": 0.0}]
    with pytest.raises(AnalysisError, match="raw_p_value"):
        service.analyze(
            {
                "experiment_id": "experiment-one",
                "execution_id": execution_id,
                "analysis_config": config,
            },
            project_id="personal",
        )


def test_analysis_holds_on_legacy_metadata_and_never_defaults_trace_complete(
    tmp_path,
) -> None:
    service, execution_id = _service(tmp_path)
    request = {
        "experiment_id": "experiment-one",
        "execution_id": execution_id,
        "analysis_config": _configuration(),
    }
    with service.repository.transaction() as conn:
        metadata = dict(conn.execute(select(episodes.c.metadata_json)).scalar_one())
        metadata.pop("analysis_pair_id")
        conn.execute(update(episodes).values(metadata_json=metadata))
    with pytest.raises(AnalysisError, match="explicit durable analysis-unit"):
        service.analyze(request, project_id="personal")

    with service.repository.transaction() as conn:
        metadata["analysis_pair_id"] = "a" * 64
        conn.execute(update(episodes).values(metadata_json=metadata))
        attempt_id = conn.execute(select(attempts.c.id)).scalar_one()
        result = dict(conn.execute(select(attempts.c.result_metadata)).scalar_one())
        result.pop("trace_complete")
        conn.execute(
            update(attempts)
            .where(attempts.c.id == attempt_id)
            .values(result_metadata=result)
        )
    result = service.analyze(
        {
            "experiment_id": "experiment-one",
            "execution_id": execution_id,
            "analysis_config": _configuration(),
        },
        project_id="personal",
    )
    assert result["adequacy"]["trace_completeness"] == 0.0


def test_latest_unknown_usage_prevents_reconciled_cost_claim(tmp_path) -> None:
    service, execution_id = _service(tmp_path)
    with service.repository.engine.connect() as conn:
        attempt_id = conn.execute(select(attempts.c.id)).scalar_one()
    with service.repository.transaction() as conn:
        conn.execute(
            insert(usage_ledger).values(
                id="usage-aaa-reconciled",
                execution_id=execution_id,
                attempt_id=attempt_id,
                model_id="recorded",
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                context_tokens=1,
                tool_calls=0,
                cost_status="reconciled",
                cost_usd=0.1,
                actual_cost_usd=0.1,
                price_catalog_revision="prices-v1",
                provider_usage_digest="c" * 64,
            )
        )
        conn.execute(
            insert(usage_ledger).values(
                id="usage-zzz-unknown",
                execution_id=execution_id,
                attempt_id=attempt_id,
                model_id="recorded",
                cost_status="unknown",
            )
        )
    execution, rows = service.repository.analysis_execution_rows(
        "personal", "experiment-one", execution_id
    )
    assert execution is not None
    record = service._attempts("experiment-one", rows)[0]
    assert record.cost_status.value == "unknown"
    assert record.cost_usd is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("factor_assignments", {"factor-one": "on"}),
        ("provider", "other-provider"),
        (
            "budget",
            {
                "max_attempts": 1,
                "max_cost_usd": 0,
                "max_latency_seconds": 1,
                "max_tokens": 2,
                "max_tool_calls": 0,
                "max_context_tokens": 1,
            },
        ),
        ("request_hash", "9" * 64),
    ],
)
def test_analysis_holds_when_terminal_envelope_mutates_queued_identity(
    tmp_path, field: str, value: object
) -> None:
    service, execution_id = _service(tmp_path)
    _replace_terminal_envelope(service, {field: value})
    with pytest.raises(AnalysisError, match="changed immutable field"):
        service.analyze(
            {
                "experiment_id": "experiment-one",
                "execution_id": execution_id,
                "analysis_config": _configuration(),
            },
            project_id="personal",
        )


def test_analysis_holds_on_tampered_terminal_attempt_identity(tmp_path) -> None:
    service, execution_id = _service(tmp_path)
    _replace_terminal_envelope(service, {"attempt_id": "attempt-other"})
    with pytest.raises(AnalysisError, match="valid terminal envelope"):
        service.analyze(
            {
                "experiment_id": "experiment-one",
                "execution_id": execution_id,
                "analysis_config": _configuration(),
            },
            project_id="personal",
        )


def test_analysis_holds_on_terminal_output_hash_mismatch(tmp_path) -> None:
    service, execution_id = _service(tmp_path)
    _replace_terminal_envelope(service, {"response_hash": "e" * 64})
    with pytest.raises(AnalysisError, match="terminal response hash"):
        service.analyze(
            {
                "experiment_id": "experiment-one",
                "execution_id": execution_id,
                "analysis_config": _configuration(),
            },
            project_id="personal",
        )


def test_analysis_holds_when_legacy_attempt_lacks_terminal_envelope(tmp_path) -> None:
    service, execution_id = _service(tmp_path)
    with service.repository.transaction() as conn:
        attempt_id = conn.execute(select(attempts.c.id)).scalar_one()
        result = dict(conn.execute(select(attempts.c.result_metadata)).scalar_one())
        result.pop("terminal_envelope")
        conn.execute(
            update(attempts)
            .where(attempts.c.id == attempt_id)
            .values(result_metadata=result)
        )
    with pytest.raises(AnalysisError, match="worker-produced terminal envelope"):
        service.analyze(
            {
                "experiment_id": "experiment-one",
                "execution_id": execution_id,
                "analysis_config": _configuration(),
            },
            project_id="personal",
        )


def test_analysis_includes_evaluated_failed_attempt_without_output_evidence(
    tmp_path,
) -> None:
    service, execution_id = _service(tmp_path)
    with service.repository.transaction() as conn:
        attempt_id = conn.execute(select(attempts.c.id)).scalar_one()
        result = dict(conn.execute(select(attempts.c.result_metadata)).scalar_one())
        result.pop("output_artifact_digest")
        result.pop("response_hash")
        result["terminal_envelope"] = AttemptEnvelope.model_validate_json(
            json.dumps(
                dict(result["terminal_envelope"])
                | {"status": "failed", "response_hash": None}
            )
        ).model_dump(mode="json")
        conn.execute(
            update(attempts)
            .where(attempts.c.id == attempt_id)
            .values(status="failed", result_metadata=result)
        )
        evaluation = dict(conn.execute(select(evaluations)).mappings().one())
        evaluation["output_artifact_digest"] = None
        evaluation["result"] = {
            "evaluator_independent": True,
            "outcome": {
                "mission_success": 0.0,
                "auditability": 1.0,
                "severe_failures": ["adapter_failure"],
                "deterministic": {},
            },
        }
        conn.execute(
            update(evaluations)
            .where(evaluations.c.id == "evaluation-one")
            .values(
                output_artifact_digest=None,
                result=evaluation["result"],
            )
        )
    execution, rows = service.repository.analysis_execution_rows(
        "personal", "experiment-one", execution_id
    )
    assert execution is not None
    record = service._attempts("experiment-one", rows)[0]
    assert record.success is False
    assert record.severe_failures == ("adapter_failure",)


def test_analysis_retains_bound_incomplete_output_as_quality_only_observation(tmp_path) -> None:
    service, execution_id = _service(tmp_path)
    with service.repository.transaction() as conn:
        attempt_id = conn.execute(select(attempts.c.id)).scalar_one()
        result = dict(conn.execute(select(attempts.c.result_metadata)).scalar_one())
        result["terminal_envelope"] = AttemptEnvelope.model_validate_json(
            json.dumps(dict(result["terminal_envelope"]) | {"status": "incomplete"})
        ).model_dump(mode="json")
        conn.execute(
            update(attempts)
            .where(attempts.c.id == attempt_id)
            .values(status="incomplete", result_metadata=result)
        )
        evaluation = dict(conn.execute(select(evaluations)).mappings().one())
        evaluation["result"] = {
            "evaluator_independent": True,
            "exclusions": ["provider_cost_identity_claims_hold_for_incomplete_adapter_evidence"],
            "outcome": {
                "mission_success": 1.0,
                "auditability": 1.0,
                "severe_failures": [],
                "deterministic": {"quality_metric": 1.0},
            },
        }
        conn.execute(
            update(evaluations)
            .where(evaluations.c.id == "evaluation-one")
            .values(result=evaluation["result"])
        )
    execution, rows = service.repository.analysis_execution_rows(
        "personal", "experiment-one", execution_id
    )
    assert execution is not None
    record = service._attempts("experiment-one", rows)[0]
    assert record.success is False
    assert ("quality_metric", 1.0) in record.continuous_outcomes
    assert record.cost_status.value == "unknown"
    analysis = service.analyze(
        {
            "experiment_id": "experiment-one",
            "execution_id": execution_id,
            "analysis_config": _configuration(),
        },
        project_id="personal",
    )
    assert analysis["verdict"] == "HOLD"
