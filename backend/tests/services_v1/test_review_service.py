from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert, select

from adapters_v1 import AttemptInput
from artifacts_v1 import LocalArtifactStore
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.schema import (
    attempts,
    episodes,
    evaluations,
    executions,
    experiments,
    study_packs,
)
from protocol_v1 import (
    AttemptEnvelope,
    BudgetSpec,
    ExecutionProvenance,
    ScenarioSpec,
    TraceEvent,
)
from protocol_v1.canonical import canonical_json, sha256, sha256_bytes
from services_v1 import ReviewError, ReviewService

NOW = datetime(2026, 8, 14, tzinfo=UTC)


def _artifact(repository: ArenaRepository, store: LocalArtifactStore, content: bytes) -> str:
    digest = store.put_bytes(content)
    repository.register_artifact(digest, size_bytes=len(content), storage_uri=store.uri_for(digest))
    return digest


def _grader_plan() -> dict:
    return {
        "bindings": [
            {"metric_id": "state", "weight": 0.7, "kind": "deterministic", "installation": {"grader_id": "state", "version": "1", "digest": "c" * 64, "trusted": True}},
            {"metric_id": "quality", "weight": 0.15, "kind": "qualitative", "installation": {"grader_id": "quality", "version": "1", "digest": "d" * 64, "trusted": True}},
            {"metric_id": "evidence", "weight": 0.15, "kind": "qualitative", "installation": {"grader_id": "evidence", "version": "1", "digest": "e" * 64, "trusted": True}},
        ],
        "human_calibration_receipt": None,
    }


def _rubric() -> dict:
    content = {
        "rubric_id": "answer-quality", "version": "1.0.0",
        "dimensions": [
            {"metric_id": "quality", "instruction": "Assess whether the answer directly and correctly addresses the task.", "anchor_0": "Does not address the task or is materially incorrect.", "anchor_1": "Directly and correctly addresses the task."},
            {"metric_id": "evidence", "instruction": "Assess whether the answer gives sufficient task-grounded support.", "anchor_0": "Provides no task-grounded support.", "anchor_1": "Provides clear task-grounded support."},
        ],
    }
    return {**content, "digest": sha256(content)}


def _service(tmp_path: Path, *, output: str = "reviewable response") -> tuple[ReviewService, ArenaRepository, LocalArtifactStore]:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    repository.create_project("Other", project_id="other")
    store = LocalArtifactStore(tmp_path / "artifacts")
    pack_digest = _artifact(repository, store, b"pack")
    response = output.encode("utf-8")
    envelope = AttemptEnvelope(
        attempt_id="attempt", episode_id="episode", ordinal=1, provider_model="recorded", provider="test",
        harness_id="harness-private", factor_assignments={"treatment_private": "control"},
        budget=BudgetSpec(max_attempts=1, max_cost_usd=1.0, max_latency_seconds=5.0, max_tokens=10, max_tool_calls=0, max_context_tokens=10),
        provenance=ExecutionProvenance(
            code_revision="fixture", code_hash="a" * 64, runtime_image="fixture", runtime_image_hash="a" * 64,
            environment_hash="a" * 64, prompt_hash="a" * 64, context_hash="a" * 64, tool_hash="a" * 64,
            source_refs=({"source_uri": "fixture://source", "content_hash": "a" * 64},), captured_at=NOW,
        ),
        request_hash="a" * 64, response_hash=sha256_bytes(response), status="completed", queued_at=NOW, started_at=NOW, completed_at=NOW,
    )
    input_value = AttemptInput.bind(ScenarioSpec(scenario_id="scenario", title="Synthetic task", task_family="fixture", prompt="Give the reviewer-safe answer.", source_label="synthetic"), envelope)
    input_digest = _artifact(repository, store, canonical_json(input_value.model_dump(mode="json")))
    output_digest = _artifact(repository, store, response)
    event = TraceEvent(
        trace_id="trace", episode_id="episode", attempt_id="attempt", sequence=0, actor="model", event_type="response",
        timestamp=NOW, monotonic_time=0.0, payload={"summary": "response delivered"}, payload_hash=sha256({"summary": "response delivered"}),
    )
    trace_digest = _artifact(repository, store, canonical_json([event.model_dump(mode="json")]))
    result = {"record": {"evaluation_id": "evaluation-attempt", "outcome": "private"}}
    result_bytes = canonical_json(result)
    result_digest = _artifact(repository, store, result_bytes)
    with repository.transaction() as conn:
        conn.execute(insert(study_packs).values(id="pack", project_id="personal", pack_key="pack", version="1.0.0", content_digest=pack_digest))
        conn.execute(insert(experiments).values(id="experiment", project_id="personal", study_pack_id="pack", name="test", protocol_version="1", definition={}))
        conn.execute(insert(executions).values(id="execution", experiment_id="experiment", status="completed", parameters={}))
        conn.execute(insert(episodes).values(id="episode", execution_id="execution", ordinal=0, scenario_id="scenario", metadata_json={}))
        conn.execute(insert(attempts).values(id="attempt", episode_id="episode", ordinal=0, status="completed", request_metadata={}, result_metadata={
            "input_artifact_digest": input_digest, "output_artifact_digest": output_digest, "trace_artifact_digest": trace_digest,
        }))
        conn.execute(insert(evaluations).values(
            id="evaluation-attempt", attempt_id="attempt", project_id="personal", evaluator="offline-evaluator", evaluator_version="1", evaluator_digest="b" * 64,
            score=0.5, result=result, input_artifact_digest=input_digest, output_artifact_digest=output_digest,
            trace_artifact_digest=trace_digest, grader_plan=_grader_plan(), result_hash=sha256_bytes(result_bytes), result_artifact_digest=result_digest,
        ))
    return ReviewService(repository, store, personal_project_id="personal"), repository, store


def _payload() -> dict:
    return {
        "batch_id": "batch-one", "protocol_hash": "a" * 64,
        "evaluator": {"evaluator_id": "offline-evaluator", "version": "1", "digest": "b" * 64},
        "grader_plan": _grader_plan(), "rubric": _rubric(), "annotator_pseudonyms": ["red", "blue", "green"],
        "items": [{"item_id": "item-one", "attempt_id": "attempt"}],
    }


def _assignment(service: ReviewService, pseudonym: str) -> str:
    return service.batch_view("batch-one", pseudonym, project_id=None)["assignments"][0]["assignment_id"]


def test_durable_blind_flow_retrieves_content_and_completes_protocol_only(tmp_path: Path) -> None:
    service, repository, _store = _service(tmp_path)
    before = repository.attempt_evaluation_source("personal", "attempt")
    created = service.create_annotation_batch(_payload(), project_id=None)
    assert created["status"] == "PENDING" and created["identity_state"] == "identity_unverified"
    assert created["human_calibration_receipt"] is None and created["human_validated"] is False
    assert repository.attempt_evaluation_source("personal", "attempt") == before
    with repository.engine.connect() as conn:
        assert len(conn.execute(select(evaluations)).mappings().all()) == 1
    red = _assignment(service, "red")
    assignment = service.assignment_view("batch-one", red, "red", project_id=None)
    content = assignment["blinded_content"]
    assert content["task"]["prompt"] == "Give the reviewer-safe answer." and content["output"] == "reviewable response"
    assert content["trace_summary"] == {"event_count": 1, "event_types": ["response"]}
    assert content["rubric"]["dimensions"][0]["anchor_0"].startswith("Does not")
    assert content["rubric"]["dimensions"][1]["instruction"].startswith("Assess")
    assert "harness" not in str(content).casefold() and "treatment" not in str(content).casefold()
    payload = {"assignment_id": red, "annotator_pseudonym": "red", "dimension_scores": {"quality": 0.0, "evidence": 0.5}}
    with ThreadPoolExecutor(max_workers=2) as executor:
        replays = list(executor.map(lambda _: service.submit_annotation("batch-one", payload, project_id=None)["idempotent_replay"], range(2)))
    assert sorted(replays) == [False, True]
    for pseudonym in ("blue", "green"):
        service.submit_annotation("batch-one", {"assignment_id": _assignment(service, pseudonym), "annotator_pseudonym": pseudonym, "dimension_scores": {"quality": 1.0, "evidence": 0.5}}, project_id=None)
    needs = service.batch_view("batch-one", "red", project_id=None)
    assert needs["status"] == "NEEDS_ADJUDICATION" and needs["conflicted_dimensions"] == {"item-one": ["quality"]}
    adjudication = {"item_id": "item-one", "adjudicator_pseudonym": "lead", "final_scores": {"quality": 1.0}, "decision": "accept", "rationale": "resolved against blinded evidence", "evidence_artifact_digest": assignment["blind_payload_digest"]}
    with pytest.raises(ReviewError, match="conflicted rubric dimensions"):
        service.submit_adjudication("batch-one", {**adjudication, "final_scores": {"quality": 1.0, "evidence": 1.0}}, project_id=None)
    assert service.submit_adjudication("batch-one", adjudication, project_id=None)["status"] == "COMPLETE"
    assert service.submit_adjudication("batch-one", adjudication, project_id=None)["idempotent_replay"] is True
    stored = repository.review_adjudications("personal", "batch-one")[0]
    assert stored["dimension_scores"] == {"quality": 1.0}
    assert stored["final_score"] == 1.0 and stored["final_score_semantics"] == "mean_summary_only"


def test_creation_fails_closed_for_caller_evidence_leaks_and_incomplete_evaluation(tmp_path: Path) -> None:
    service, repository, _store = _service(tmp_path)
    for field in ("blind_payload_digest", "input_artifact_digest", "output_artifact_digest", "trace_artifact_digest"):
        leaked = _payload()
        leaked["items"][0][field] = "d" * 64
        with pytest.raises(ReviewError, match="derived only"):
            service.create_annotation_batch(leaked, project_id=None)
    leaked = _payload()
    leaked["items"][0]["nested"] = {"treatment_id": "private"}
    with pytest.raises(ReviewError, match="forbidden"):
        service.create_annotation_batch(leaked, project_id=None)
    with repository.transaction() as conn:
        conn.execute(evaluations.delete())
    with pytest.raises(ReviewError, match="durable immutable evaluation"):
        service.create_annotation_batch(_payload(), project_id=None)


def test_rubric_digest_dimension_binding_and_submission_dimensions_fail_closed(tmp_path: Path) -> None:
    service, _repository, _store = _service(tmp_path)
    bad_digest = _payload()
    bad_digest["rubric"]["digest"] = "f" * 64
    with pytest.raises(ReviewError, match="only blind assignments"):
        service.create_annotation_batch(bad_digest, project_id=None)
    missing = _payload()
    missing["rubric"]["dimensions"] = missing["rubric"]["dimensions"][:1]
    content = {key: value for key, value in missing["rubric"].items() if key != "digest"}
    missing["rubric"]["digest"] = sha256(content)
    with pytest.raises(ReviewError, match="only blind assignments"):
        service.create_annotation_batch(missing, project_id=None)
    leaking = _payload()
    leaking["rubric"]["dimensions"][0]["instruction"] = "Assess the private scaffold treatment."
    content = {key: value for key, value in leaking["rubric"].items() if key != "digest"}
    leaking["rubric"]["digest"] = sha256(content)
    with pytest.raises(ReviewError, match="only blind assignments"):
        service.create_annotation_batch(leaking, project_id=None)
    service.create_annotation_batch(_payload(), project_id=None)
    red = _assignment(service, "red")
    for scores in ({"quality": 0.5}, {"quality": 0.5, "evidence": 0.5, "extra": 0.5}):
        with pytest.raises(ReviewError, match="exactly the rubric dimensions"):
            service.submit_annotation("batch-one", {"assignment_id": red, "annotator_pseudonym": "red", "dimension_scores": scores}, project_id=None)


def test_rejects_recursive_output_leak_project_reuse_and_tampered_artifact(tmp_path: Path) -> None:
    leaking, _repository, _store = _service(tmp_path / "leaking", output='{"nested":{"adapter_id":"private"}}')
    with pytest.raises(ReviewError, match="forbidden"):
        leaking.create_annotation_batch(_payload(), project_id=None)

    service, repository, store = _service(tmp_path / "safe")
    created = service.create_annotation_batch(_payload(), project_id=None)
    red = _assignment(service, "red")
    assignment = service.assignment_view("batch-one", red, "red", project_id=None)
    with pytest.raises(ReviewError, match="not found"):
        service.assignment_view("batch-one", red, "red", project_id="other")
    unrelated = _artifact(repository, store, b"globally registered but not project-bound")
    service.submit_annotation("batch-one", {"assignment_id": red, "annotator_pseudonym": "red", "dimension_scores": {"quality": 0.0, "evidence": 0.5}}, project_id=None)
    for pseudonym in ("blue", "green"):
        service.submit_annotation("batch-one", {"assignment_id": _assignment(service, pseudonym), "annotator_pseudonym": pseudonym, "dimension_scores": {"quality": 1.0, "evidence": 0.5}}, project_id=None)
    rejected = {"item_id": "item-one", "adjudicator_pseudonym": "lead", "final_scores": {"quality": 1.0}, "decision": "accept", "rationale": "wrong globally registered evidence", "evidence_artifact_digest": unrelated}
    with pytest.raises(ReviewError, match="bound to this project"):
        service.submit_adjudication("batch-one", rejected, project_id=None)
    store._path(assignment["blind_payload_digest"]).write_bytes(b"tampered")
    with pytest.raises(ReviewError, match="registered digest"):
        service.assignment_view("batch-one", red, "red", project_id=None)
    assert created["protocol_complete"] is False


def test_batch_replays_are_immutable_after_derived_payload_creation(tmp_path: Path) -> None:
    service, _repository, _store = _service(tmp_path)
    original = _payload()
    assert service.create_annotation_batch(original, project_id=None)["idempotent_replay"] is False
    assert service.create_annotation_batch(original, project_id=None)["idempotent_replay"] is True
    changed = deepcopy(original)
    changed["evaluator"]["version"] = "2"
    with pytest.raises(ReviewError, match="immutable evaluation"):
        service.create_annotation_batch(changed, project_id=None)
