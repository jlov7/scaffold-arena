from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy import insert, update

from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.schema import (
    attempts,
    episodes,
    executions,
    experiments,
    study_packs,
)
from services_v1.trace_lab import TraceLabError, TraceLabService

HASH = "a" * 64


def _service(tmp_path) -> tuple[TraceLabService, ArenaRepository]:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    repository.create_project("Other", project_id="other")
    repository.register_artifact(HASH, size_bytes=1, storage_uri="test://pack")
    with repository.transaction() as conn:
        conn.execute(insert(study_packs).values(id="pack-one", project_id="personal", pack_key="pack", version="1.0.0", content_digest=HASH))
        conn.execute(insert(experiments).values(id="experiment-one", project_id="personal", study_pack_id="pack-one", name="one", protocol_version="1", definition={}))
        conn.execute(insert(experiments).values(id="experiment-two", project_id="personal", study_pack_id="pack-one", name="two", protocol_version="1", definition={}))
        for execution_id, experiment_id, attempt_id in (
            ("execution-left", "experiment-one", "attempt-left"),
            ("execution-right", "experiment-one", "attempt-right"),
            ("execution-other", "experiment-two", "attempt-other"),
        ):
            conn.execute(insert(executions).values(id=execution_id, experiment_id=experiment_id, status="completed", parameters={}))
            episode_id = f"episode-{attempt_id.removeprefix('attempt-')}"
            conn.execute(insert(episodes).values(id=episode_id, execution_id=execution_id, ordinal=0, metadata_json={}))
            conn.execute(insert(attempts).values(id=attempt_id, episode_id=episode_id, ordinal=0, status="completed", request_metadata={}, result_metadata={"trace_complete": True}))
    return TraceLabService(repository, personal_project_id="personal"), repository


def _event(
    attempt_id: str,
    sequence: int,
    event_type: str,
    *,
    seconds: int = 0,
    state: str | None = None,
    payload: dict | None = None,
    payload_hash: str = HASH,
) -> dict:
    minute, second = divmod(seconds, 60)
    value = {
        "protocol_version": "1.0", "trace_id": f"trace-{attempt_id.removeprefix('attempt-')}",
        "episode_id": f"episode-{attempt_id.removeprefix('attempt-')}", "attempt_id": attempt_id,
        "sequence": sequence, "actor": "model", "event_type": event_type,
        "timestamp": f"2026-08-14T00:{minute:02d}:{second:02d}Z", "monotonic_time": float(seconds),
        "payload": payload or {}, "payload_hash": payload_hash,
    }
    if state is not None:
        value["state_ref"] = {"state_id": state, "snapshot_hash": HASH}
    return value


def _append_pair(repository: ArenaRepository, *, right_events: list[dict] | None = None) -> None:
    left = [_event("attempt-left", 0, "request"), _event("attempt-left", 1, "tool_call", state="state-left"), _event("attempt-left", 2, "response")]
    right = right_events or [_event("attempt-right", 0, "request", seconds=300), _event("attempt-right", 1, "tool_call", seconds=302, state="state-right"), _event("attempt-right", 2, "response", seconds=304)]
    for event in left + right:
        repository.append_attempt_event(event["attempt_id"], "trace", event)


def test_trace_lab_is_stable_clock_skew_tolerant_and_never_leaks_payload_secrets(tmp_path) -> None:
    service, repository = _service(tmp_path)
    right = [_event("attempt-right", 0, "request", seconds=300, payload={"api_key": "do-not-leak"}), _event("attempt-right", 1, "tool_call", seconds=302, state="state-right", payload={"access_token": "do-not-leak"}), _event("attempt-right", 2, "response", seconds=304)]
    _append_pair(repository, right_events=right)
    payload = {"left_attempt_id": "attempt-left", "right_attempt_id": "attempt-right"}
    first = service.analyze(payload, project_id=None)
    second = service.analyze(deepcopy(payload), project_id=None)
    assert first["analysis_digest"] == second["analysis_digest"]
    assert first["first_meaningful_divergence"]["found"] is False
    assert first["alignment"]["clock_skew_tolerant"] is True
    assert first["alignment"]["source_digest"]
    assert len(first["alignment"]["rows"]) == 3
    assert {row["status"] for row in first["alignment"]["rows"]} == {"MATCH"}
    assert first["causal_label"] == "DIAGNOSTIC_ONLY"
    assert "do-not-leak" not in str(first)
    assert "payload" not in str(first["alignment"]["rows"]).lower()
    assert first["coverage"] == {"numerator": 3, "denominator": 3, "exclusions": []}


def test_trace_lab_rejects_same_attempt_cross_project_and_cross_experiment(tmp_path) -> None:
    service, repository = _service(tmp_path)
    _append_pair(repository)
    repository.append_attempt_event("attempt-other", "trace", _event("attempt-other", 0, "request"))
    with pytest.raises(TraceLabError, match="distinct"):
        service.analyze({"left_attempt_id": "attempt-left", "right_attempt_id": "attempt-left"}, project_id=None)
    with pytest.raises(TraceLabError) as cross_project:
        service.analyze({"left_attempt_id": "attempt-left", "right_attempt_id": "attempt-right"}, project_id="other")
    assert cross_project.value.status_code == 404
    with pytest.raises(TraceLabError, match="one persisted experiment"):
        service.analyze({"left_attempt_id": "attempt-left", "right_attempt_id": "attempt-other"}, project_id=None)


def test_trace_lab_holds_gapped_traces_unless_explicit_diagnostic_partial_mode(tmp_path) -> None:
    service, repository = _service(tmp_path)
    right = [_event("attempt-right", 0, "request"), _event("attempt-right", 2, "response")]
    _append_pair(repository, right_events=right)
    payload = {"left_attempt_id": "attempt-left", "right_attempt_id": "attempt-right"}
    with pytest.raises(TraceLabError) as hold:
        service.analyze(payload, project_id=None)
    assert hold.value.code == "partial_trace_hold" and hold.value.status_code == 409
    diagnostic = service.analyze({**payload, "diagnostic_partial_mode": True}, project_id=None)
    assert diagnostic["mode"] == "DIAGNOSTIC_PARTIAL"
    assert "attempt-right:trace_sequence_gap" in diagnostic["coverage"]["exclusions"]


def test_trace_lab_normalizes_reordered_events_and_finds_a_diagnostic_divergence(tmp_path) -> None:
    service, repository = _service(tmp_path)
    right = [
        _event("attempt-right", 0, "request"),
        _event("attempt-right", 2, "tool_call"),
        _event("attempt-right", 1, "response", state="state-right"),
    ]
    _append_pair(repository, right_events=right)
    diagnostic = service.analyze({"left_attempt_id": "attempt-left", "right_attempt_id": "attempt-right", "diagnostic_partial_mode": True}, project_id=None)
    assert diagnostic["first_meaningful_divergence"]["found"] is True
    assert diagnostic["first_meaningful_divergence"]["label"] == "DIAGNOSTIC_ONLY"
    assert diagnostic["first_meaningful_divergence"]["state_before"] == {"left": None, "right": None}
    assert diagnostic["first_meaningful_divergence"]["state_after"]["left"]["state_id"] == "state-left"
    assert diagnostic["first_meaningful_divergence"]["state_after"]["right"]["state_id"] == "state-right"
    assert "attempt-right:persisted_trace_order_reordered" in diagnostic["coverage"]["exclusions"]


def test_trace_lab_never_infers_completeness_from_a_contiguous_subset(tmp_path) -> None:
    service, repository = _service(tmp_path)
    _append_pair(repository)
    with repository.transaction() as conn:
        conn.execute(update(attempts).where(attempts.c.id == "attempt-right").values(result_metadata={}))
    payload = {"left_attempt_id": "attempt-left", "right_attempt_id": "attempt-right"}
    with pytest.raises(TraceLabError) as hold:
        service.analyze(payload, project_id=None)
    assert hold.value.code == "partial_trace_hold"
    diagnostic = service.analyze({**payload, "diagnostic_partial_mode": True}, project_id=None)
    assert "attempt-right:trace_completeness_unverified" in diagnostic["coverage"]["exclusions"]


def test_trace_lab_rejects_caller_supplied_events_payloads_and_outcomes(tmp_path) -> None:
    service, repository = _service(tmp_path)
    _append_pair(repository)
    with pytest.raises(TraceLabError, match="only"):
        service.analyze({"left_attempt_id": "attempt-left", "right_attempt_id": "attempt-right", "events": []}, project_id=None)


def test_trace_lab_returns_content_aware_rows_and_isolates_inserted_events(tmp_path) -> None:
    service, repository = _service(tmp_path)
    inserted_hash = "b" * 64
    right = [
        _event("attempt-right", 0, "request", seconds=300),
        _event("attempt-right", 1, "state", seconds=301, state="inserted-state", payload_hash=inserted_hash),
        _event("attempt-right", 2, "tool_call", seconds=302, state="state-right"),
        _event("attempt-right", 3, "response", seconds=304),
    ]
    _append_pair(repository, right_events=right)

    result = service.analyze(
        {"left_attempt_id": "attempt-left", "right_attempt_id": "attempt-right"},
        project_id=None,
    )

    rows = result["alignment"]["rows"]
    assert [row["status"] for row in rows] == [
        "MATCH",
        "RIGHT_ONLY",
        "MATCH",
        "MATCH",
    ]
    inserted = rows[1]
    assert inserted["anchor"] == "state_change"
    assert inserted["left"] is None
    assert inserted["right"]["observation_digest"] == inserted_hash
    assert result["first_meaningful_divergence"]["alignment_position"] == 1
    assert result["first_meaningful_divergence"]["left_event_id"] is None
    assert result["first_meaningful_divergence"]["right_event_id"] == inserted["right"]["event_id"]


def test_trace_lab_marks_same_anchor_content_changes_without_returning_payloads(tmp_path) -> None:
    service, repository = _service(tmp_path)
    changed_hash = "c" * 64
    right = [
        _event("attempt-right", 0, "request", payload={"secret": "not-returned"}),
        _event("attempt-right", 1, "tool_call", state="state-right", payload={"password": "not-returned"}, payload_hash=changed_hash),
        _event("attempt-right", 2, "response"),
    ]
    _append_pair(repository, right_events=right)

    result = service.analyze(
        {"left_attempt_id": "attempt-left", "right_attempt_id": "attempt-right"},
        project_id=None,
    )

    assert result["alignment"]["content_differences"] == 1
    row = result["alignment"]["rows"][1]
    assert row["status"] == "CONTENT_DIFFERENCE"
    assert row["left"]["observation_digest"] == HASH
    assert row["right"]["observation_digest"] == changed_hash
    assert "not-returned" not in str(result)
    assert result["first_meaningful_divergence"]["alignment_position"] == 1
    assert "observation digests differ" in result["first_meaningful_divergence"]["reason"]


def test_trace_lab_holds_before_quadratic_alignment_above_the_event_limit(tmp_path) -> None:
    service, repository = _service(tmp_path)
    for sequence in range(1_025):
        repository.append_attempt_event(
            "attempt-left",
            "trace",
            _event("attempt-left", sequence, "state", seconds=sequence),
        )
    repository.append_attempt_event(
        "attempt-right", "trace", _event("attempt-right", 0, "state")
    )

    with pytest.raises(TraceLabError) as hold:
        service.analyze(
            {"left_attempt_id": "attempt-left", "right_attempt_id": "attempt-right"},
            project_id=None,
        )
    assert hold.value.code == "trace_too_large"
    assert hold.value.status_code == 409
