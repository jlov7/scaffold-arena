from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.forge import router
from artifacts_v1 import LocalArtifactStore
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from services_v1.forge import ExperimentPlannerService, ForgeService, ProcessSafetyService
from tests.services_v1.test_forge_planner_process_safety import evaluation, planner, process_safety, proposal


def client(tmp_path) -> TestClient:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    store = LocalArtifactStore(tmp_path / "artifacts")
    app = FastAPI()
    app.state.forge_service = ForgeService(repository, store, personal_project_id="personal")
    app.state.experiment_planner_service = ExperimentPlannerService(repository, store, personal_project_id="personal")
    app.state.process_safety_service = ProcessSafetyService(repository, store, personal_project_id="personal")
    app.include_router(router)
    return TestClient(app)


def test_forge_api_requires_owner_approval_and_never_returns_execution_authority(tmp_path) -> None:
    arena = client(tmp_path)
    created = arena.post("/api/v1/forge/proposals", json=proposal())
    assert created.status_code == 200
    candidate = created.json()
    assert candidate["state"] == "PENDING_APPROVAL"
    assert candidate["execution_started"] is False
    rejected = arena.post("/api/v1/forge/evaluations", json={})
    assert rejected.status_code == 400
    approval = {
        "proposal_digest": candidate["proposal_digest"], "approver_identity": "approver-one", "authority_kind": "human",
        "decision": "APPROVED", "policy_digest": f"sha256:{'a' * 64}", "decision_evidence_digest": f"sha256:{'b' * 64}",
        "execution_authorized": False, "merge_authorized": False,
    }
    assert arena.post(f"/api/v1/forge/proposals/{candidate['proposal_digest']}/approval", json=approval).status_code == 200
    safety = arena.post("/api/v1/process-safety-reports", json=process_safety())
    assert safety.status_code == 200
    receipt = arena.post("/api/v1/forge/evaluations", json=evaluation(candidate["proposal_digest"], safety.json()["report_digest"]))
    assert receipt.status_code == 200
    assert receipt.json()["automatic_merge"] is False
    assert arena.get(f"/api/v1/forge/evolution-receipts/{receipt.json()['receipt_digest']}").json()["receipt_digest"] == receipt.json()["receipt_digest"]


def test_planner_and_process_safety_api_are_provider_free_and_public_errors_are_redacted(tmp_path) -> None:
    arena = client(tmp_path)
    plan = arena.post("/api/v1/experiment-plans/next-best", json=planner())
    assert plan.status_code == 200
    assert plan.json()["execution_started"] is False
    assert plan.json()["network_requested"] is False
    invalid = arena.post("/api/v1/process-safety-reports", json={"sensitive": "do not echo"})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["message"] == "The request is invalid."
