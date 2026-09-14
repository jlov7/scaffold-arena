from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.counterfactual import router
from artifacts_v1 import LocalArtifactStore
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from services_v1.counterfactual import CounterfactualReplayService, HarnessCIService


_EXAMPLE = Path(__file__).parents[3] / "examples" / "counterfactual-replay" / "fixture-replay.json"


def _fixture() -> dict:
    return json.loads(_EXAMPLE.read_text(encoding="utf-8"))


def _client(tmp_path: Path) -> TestClient:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    store = LocalArtifactStore(tmp_path / "artifacts")
    replays = CounterfactualReplayService(repository, store, personal_project_id="personal")
    app = FastAPI()
    app.state.counterfactual_replay_service = replays
    app.state.harness_ci_service = HarnessCIService(repository, store, personal_project_id="personal", replay_service=replays)
    app.include_router(router)
    return TestClient(app)


def test_counterfactual_replay_api_is_fixture_safe_and_project_scoped(tmp_path: Path) -> None:
    client = _client(tmp_path)
    created = client.post("/api/v1/counterfactual-replays", json=_fixture())

    assert created.status_code == 200
    body = created.json()
    assert body["verdict"] == "HOLD"
    assert body["usage_state"] == "unknown"
    assert body["provider_execution_started"] is False
    assert client.get(f"/api/v1/counterfactual/replays/{body['report_digest']}").json()["report_digest"] == body["report_digest"]

    invalid = client.post("/api/v1/counterfactual-replays", json={"mode": "fixture"})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "counterfactual_contract_invalid"


def test_harness_ci_api_returns_json_and_comment_body_artifact_payload(tmp_path: Path) -> None:
    client = _client(tmp_path)
    replay = client.post("/api/v1/counterfactual-replays", json=_fixture()).json()
    requested = client.post(
        "/api/v1/harness-ci/checks",
        json={
            "replay_report_digest": replay["report_digest"],
            "base_source_digest": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
            "candidate_source_digest": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
            "source_changes": [{"path": "harness/config.ts", "diff_text": "+ context compaction"}],
            "policy": {"required_cohorts": ["development"], "unknown_usage": "hold"},
        },
    )

    assert requested.status_code == 200
    report = requested.json()
    assert report["verdict"] == "HOLD"
    assert "## Harness CI" in report["step_summary"]
    assert report["pr_comment_body"] == report["step_summary"]
    assert report["semantic_diff"]["recommended_packs"] == ["context-survival-v1"]
    assert client.get(f"/api/v1/harness-ci-reports/{report['report_digest']}").json()["report_digest"] == report["report_digest"]
