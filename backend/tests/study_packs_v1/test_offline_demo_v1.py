from __future__ import annotations

import io
import zipfile
from pathlib import Path

from adapters_v1.offline_fixture import bundled_study_pack_root
from artifacts_v1 import LocalArtifactStore
from evaluation_v1 import (
    EvaluationContext,
    TrustedGraderRegistry,
    compile_grader_plan,
    evaluate_attempt,
)
from factors_v1 import CAPABLE_RECORDED_PROFILE, compile_recipe
from persistence_v1 import ArenaRepository, create_persistence_engine
from persistence_v1.schema import metadata
from protocol_v1 import expand_design, load_study_pack
from protocol_v1.canonical import sha256_bytes
from services_v1 import ProtocolRegistryService, StudyPackExportService

PACK_ROOT = Path(__file__).resolve().parents[3] / "study_packs" / "offline-demo-v1"


def pack_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path in sorted(PACK_ROOT.rglob("*")):
            if path.is_file():
                archive.writestr(path.relative_to(PACK_ROOT).as_posix(), path.read_bytes())
    return output.getvalue()


def service(tmp_path: Path) -> tuple[ProtocolRegistryService, StudyPackExportService]:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    registry = ProtocolRegistryService(repository, artifacts, personal_project_id="personal")
    return registry, StudyPackExportService(repository, artifacts, personal_project_id="personal")


def scenario(pack, scenario_id: str):
    return next(item for item in pack.scenarios if item.scenario_id == scenario_id)


def test_packaged_offline_demo_matches_public_study_pack() -> None:
    packaged = bundled_study_pack_root()
    public_files = {
        path.relative_to(PACK_ROOT).as_posix(): path.read_bytes()
        for path in PACK_ROOT.rglob("*")
        if path.is_file()
    }
    packaged_files = {
        path.relative_to(packaged).as_posix(): path.read_bytes()
        for path in packaged.rglob("*")
        if path.is_file()
    }
    assert packaged_files == public_files


def test_offline_demo_pack_registry_freeze_expansion_and_controls(tmp_path: Path) -> None:
    pack = load_study_pack(PACK_ROOT)
    assert pack.study_pack_id == "offline-demo-v1"
    assert pack.harnesses[0].adapter == "recorded"
    assert pack.harnesses[0].claim_eligibility == "fixture_only"
    assert pack.harnesses[0].adapter_identity == "offline-demo-fixture"
    assert pack.harnesses[0].configuration["fixture_truth_table_sha256"] == sha256_bytes(
        (PACK_ROOT / "fixtures/runtime-truth-table.json").read_bytes()
    )
    assert pack.allowed_claims == (
        "Synthetic recorded-fixture demonstration only.",
        "Local protocol import, freeze, expansion, and deterministic-control behavior only.",
    )

    assert (PACK_ROOT / pack.preregistration.reference_uri).is_file()
    assert sha256_bytes((PACK_ROOT / pack.preregistration.reference_uri).read_bytes()) == pack.preregistration.content_hash
    for selected in pack.scenarios:
        for source in selected.evidence_sources:
            source_path = PACK_ROOT / source.source_uri
            assert source_path.is_file()
            assert sha256_bytes(source_path.read_bytes()) == source.content_hash
        assert selected.reference_solution is not None
        assert selected.output_contract is not None
        assert selected.final_state_oracle is not None
    assert sha256_bytes((PACK_ROOT / "fixtures/initial-state.json").read_bytes()) == scenario(pack, "candidate-clean").initial_state.snapshot_hash
    assert sha256_bytes((PACK_ROOT / "fixtures/reference-solutions/expected-response.json").read_bytes()) == scenario(pack, "candidate-clean").reference_solution.artifact_hash
    assert sha256_bytes((PACK_ROOT / "fixtures/contracts/response.schema.json").read_bytes()) == scenario(pack, "candidate-clean").output_contract.schema_hash

    registry, exporter = service(tmp_path)
    bundle = pack_zip()
    validation = registry.validate_pack(bundle, "application/zip")
    assert validation["valid"] is True
    assert validation["readiness"]["verdict"] == "PASS"
    imported = registry.import_pack(bundle, "application/zip", project_id="personal")
    exported = exporter.export_study_pack(pack.study_pack_id, pack.version, project_id="personal")
    assert registry.validate_pack(exported.content, "application/zip")["content_digest"] == imported["content_digest"]

    template = pack.experiments[0].model_dump(mode="json")
    created = registry.create_experiment(template, project_id="personal")
    frozen = registry.freeze(created["experiment_id"], project_id="personal")
    assert frozen["frozen"] is True
    preflight = registry.preflight(created["experiment_id"], project_id="personal")
    assert preflight["verdict"] == "PASS"
    assert preflight["design_expansion_count"] == 16
    assert preflight["expected_attempts"] == 80
    assert preflight["claim_ceiling"] == "fixture exploration only; personal/local authority"

    experiment = pack.experiments[0]
    analysis = experiment.extensions["org.scaffold-arena.analysis-v1"]
    assert len(analysis["primary_main_effects"]) == 4
    assert len(analysis["secondary_interactions"]) == 1
    arms = expand_design(experiment)
    assert len(arms) == 16
    assert len({tuple(sorted(arm.items())) for arm in arms}) == 16
    for arm in arms:
        recipe = compile_recipe(arm, factors=experiment.factors, profile=CAPABLE_RECORDED_PROFILE)
        assert recipe.assignment == arm

    evaluator = TrustedGraderRegistry()
    positive = evaluate_attempt(
        attempt={"episode_id": "positive-control"},
        output=(PACK_ROOT / "fixtures/outputs/positive-control.json").read_text(),
        context=EvaluationContext(state_refs={"case_state": "completed"}),
        plan=compile_grader_plan(pack, "positive-control", evaluator),
        registry=evaluator,
        trace_hash="a" * 64,
    )
    negative = evaluate_attempt(
        attempt={"episode_id": "negative-control"},
        output=(PACK_ROOT / "fixtures/outputs/negative-control.json").read_text(),
        context=EvaluationContext(state_refs={"case_state": "failed"}),
        plan=compile_grader_plan(pack, "negative-control", evaluator),
        registry=evaluator,
        trace_hash="b" * 64,
    )
    anti_cheat = evaluate_attempt(
        attempt={"episode_id": "anti-cheat-control"},
        output=(PACK_ROOT / "fixtures/outputs/anti-cheat-control.json").read_text(),
        context=EvaluationContext(state_refs={"case_state": "completed"}),
        plan=compile_grader_plan(pack, "anti-cheat-control", evaluator),
        registry=evaluator,
        trace_hash="c" * 64,
    )
    assert positive.record.outcome.mission_success == 1.0
    assert negative.record.outcome.deterministic["exact-response"] == 0.0
    assert negative.record.outcome.deterministic["final-state"] == 0.0
    assert anti_cheat.hard_gate_passed is False
    assert anti_cheat.record.outcome.mission_success == 0.0
    assert anti_cheat.record.outcome.severe_failures == ("fixture-claim-ceiling-breach",)
