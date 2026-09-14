from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from protocol_v1 import load_study_pack
from protocol_v1.scientific_completion import (
    AttemptEvidence,
    ConfirmatoryHold,
    ScientificStudy,
    build_fixture_bundle,
    canonical_study_hash,
    load_scientific_study,
    resolve_study_artifact,
    validate_evidence_matrix,
    write_fixture_bundle,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def digest(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def study(*, published: bool = False, transfer: bool = False) -> ScientificStudy:
    preregistration = {
        "artifact_uri": "fixtures/preregistration.md",
        "artifact_hash": digest("preregistration"),
        "publication_state": "public_immutable" if published else "hold_not_public",
        "publication_id": "osf.io/example" if published else None,
        "published_at": "2026-08-20T00:00:00Z" if published else None,
    }
    payload = {
        "study_id": "transfer-study" if transfer else "flagship-study",
        "study_kind": "transfer" if transfer else "flagship",
        "claim_ceiling": "Protocol and recorded-fixture readiness only; no empirical or live-provider claim.",
        "bundle_created_at": "2026-08-20T00:00:00Z",
        "preregistration": preregistration,
        "frozen_bindings": {
            "models": [{"id": "model-a", "digest": digest("model-a")}],
            "harnesses": [{"id": "harness-a", "digest": digest("harness-a")}],
            "runtimes": [{"id": "ollama-a", "kind": "ollama", "identity_digest": digest("ollama-a"), "paid_cost_policy": "zero_paid_cost_local_energy_unknown"}],
            "evaluators": [{"id": "deterministic-a", "digest": digest("deterministic-a")}],
            "sampling_digest": digest("sampling"),
            "budget_digest": digest("budget"),
            "stopping_digest": digest("stopping"),
            "exclusions_digest": digest("exclusions"),
            "severe_failure_digest": digest("severe-failure"),
            "analysis_digest": digest("analysis"),
            "multiplicity_digest": digest("multiplicity"),
        },
        "matrix": {
            "models": ["model-a"], "harnesses": ["harness-a"], "tasks": ["task-a", "task-b"],
            "domains": ["domain-a", "domain-b"], "cohorts": ["cohort-a"], "repetitions": 2,
        },
        "cohorts": [{"cohort_id": "cohort-a", "role": "flagship", "task_ids": ["task-a", "task-b"], "domain_ids": ["domain-a", "domain-b"], "model_ids": ["model-a"]}],
        "runtime_admissions": [{"runtime_id": "ollama-a", "kind": "ollama", "endpoint_identity_digest": digest("ollama-a")}],
    }
    if transfer:
        payload["matrix"]["models"] = ["model-a", "model-b"]
        payload["frozen_bindings"]["models"].append({"id": "model-b", "digest": digest("model-b")})
        payload["matrix"]["cohorts"] = ["selection", "transfer"]
        payload["cohorts"] = [
            {"cohort_id": "selection", "role": "selection", "task_ids": ["task-a"], "domain_ids": ["domain-a"], "model_ids": ["model-a"]},
            {"cohort_id": "transfer", "role": "transfer", "task_ids": ["task-b"], "domain_ids": ["domain-b"], "model_ids": ["model-b"]},
        ]
        payload["frozen_selection_receipt"] = {"receipt_hash": digest("selection-receipt"), "selection_configuration_hash": digest("selection-config"), "transfer_configuration_hash": digest("selection-config")}
        payload["no_retuning"] = True
    return ScientificStudy.model_validate_json(json.dumps(payload))


def test_canonical_hash_is_stable_and_matrix_is_complete() -> None:
    candidate = study()
    assert canonical_study_hash(candidate) == canonical_study_hash(ScientificStudy.model_validate_json(candidate.model_dump_json()))
    bundle = build_fixture_bundle(candidate)
    assert bundle["matrix"]["expected_cells"] == 8
    assert len(bundle["matrix"]["cells"]) == 8
    assert bundle["execution_path"] == "execution_v1.controller -> execution_v1.worker -> services_v1.evidence"
    assert bundle["confirmatory_status"] == "HOLD_PREREGISTRATION_NOT_PUBLIC_IMMUTABLE"


def test_declared_matrix_counts_follow_cohort_specific_axes() -> None:
    flagship = load_scientific_study(
        REPO_ROOT / "study_packs" / "flagship-prereg-v1" / "fixtures" / "scientific-study.json"
    )
    transfer = load_scientific_study(
        REPO_ROOT / "study_packs" / "transfer-prereg-v1" / "fixtures" / "scientific-study.json"
    )
    assert flagship.cell_count == 16
    assert transfer.cell_count == 4
    assert build_fixture_bundle(flagship)["matrix"]["expected_cells"] == 16
    assert build_fixture_bundle(transfer)["matrix"]["expected_cells"] == 4


def test_confirmatory_mode_fails_closed_until_preregistration_is_public() -> None:
    with pytest.raises(ConfirmatoryHold, match="public immutable"):
        build_fixture_bundle(study(), mode="confirmatory")
    assert build_fixture_bundle(study(published=True), mode="confirmatory")["confirmatory_status"] == "ADMISSION_READY_NOT_EXECUTED"


def test_transfer_requires_disjoint_cohorts_and_matching_frozen_config() -> None:
    candidate = study(transfer=True)
    assert candidate.no_retuning is True
    invalid = candidate.model_dump(mode="json")
    invalid["cohorts"][1]["task_ids"] = ["task-a", "task-b"]
    with pytest.raises(ValueError, match="disjoint"):
        ScientificStudy.model_validate_json(json.dumps(invalid))
    invalid = candidate.model_dump(mode="json")
    invalid["frozen_selection_receipt"]["transfer_configuration_hash"] = "9" * 64
    with pytest.raises(ValueError, match="equal"):
        ScientificStudy.model_validate_json(json.dumps(invalid))


def test_generic_openai_compatible_runtime_is_not_admitted() -> None:
    payload = study().model_dump(mode="json")
    payload["runtime_admissions"][0]["kind"] = "openai_compatible"
    with pytest.raises(ValueError, match="not an admissible"):
        ScientificStudy.model_validate_json(json.dumps(payload))


def test_bundle_is_collision_gated_and_contains_reproduction_command(tmp_path: Path) -> None:
    candidate = study()
    written = write_fixture_bundle(candidate, tmp_path)
    assert (written / "bundle-manifest.json").is_file()
    manifest = json.loads((written / "bundle-manifest.json").read_text())
    assert manifest["signature"]["state"] == "HOLD_EXTERNAL_KEYLESS_SIGNATURE_REQUIRED"
    assert manifest["reproduction_command"][-2:] == ["--mode", "fixture"]
    assert (written / "analysis-report-template.json").is_file()
    with pytest.raises(FileExistsError):
        write_fixture_bundle(candidate, tmp_path)


def test_bundle_bytes_are_identical_across_two_clean_output_roots(tmp_path: Path) -> None:
    candidate = study()
    first = write_fixture_bundle(candidate, tmp_path / "one")
    second = write_fixture_bundle(candidate, tmp_path / "two")
    assert {path.name for path in first.iterdir()} == {path.name for path in second.iterdir()}
    for path in first.iterdir():
        assert path.read_bytes() == (second / path.name).read_bytes()


def test_safe_artifact_resolution_rejects_traversal_and_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "study"
    fixtures = root / "fixtures"
    fixtures.mkdir(parents=True)
    artifact = fixtures / "artifact.json"
    artifact.write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    assert resolve_study_artifact(root, "fixtures/artifact.json") == artifact.resolve()
    with pytest.raises(ValueError, match="regular file"):
        resolve_study_artifact(root, "fixtures")
    with pytest.raises(ValueError, match="study root"):
        resolve_study_artifact(root, "../outside.json")
    (fixtures / "file-link.json").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        resolve_study_artifact(root, "fixtures/file-link.json")
    (root / "linked").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        resolve_study_artifact(root, "linked/outside.json")


def test_evidence_requires_complete_fixture_live_separation_and_retained_failures() -> None:
    candidate = study()
    cells = build_fixture_bundle(candidate)["matrix"]["cells"]
    records = tuple(
        AttemptEvidence(cell_id=cell["cell_id"], evidence_class="fixture", terminal_status="completed", severe_failures=())
        for cell in cells
    )
    validate_evidence_matrix(candidate, records)
    with pytest.raises(ValueError, match="provider usage"):
        AttemptEvidence(cell_id="a", evidence_class="local_live", terminal_status="completed", severe_failures=())
    with pytest.raises(ValueError, match="every matrix cell"):
        validate_evidence_matrix(candidate, records[:-1])


@pytest.mark.parametrize("pack_id", ("flagship-prereg-v1", "transfer-prereg-v1"))
def test_checked_in_scientific_packs_are_declarative_and_hold_confirmatory_dispatch(pack_id: str) -> None:
    root = REPO_ROOT / "study_packs" / pack_id
    pack = load_study_pack(root)
    assert pack.extensions["org.scaffold-arena.scientific-v1"]["publication_state"] == "hold_not_public"
    draft = load_scientific_study(root / "fixtures/scientific-study.json")
    assert build_fixture_bundle(draft)["confirmatory_status"] == "HOLD_PREREGISTRATION_NOT_PUBLIC_IMMUTABLE"
    with pytest.raises(ConfirmatoryHold, match="HOLD_PREREGISTRATION_NOT_PUBLIC_IMMUTABLE"):
        build_fixture_bundle(draft, mode="confirmatory")
    public = draft.model_dump(mode="json")
    public["preregistration"].update(
        publication_state="public_immutable",
        publication_id="osf.io/example",
        published_at="2026-08-20T00:00:00Z",
    )
    with pytest.raises(ConfirmatoryHold, match="HOLD_PLACEHOLDER_FROZEN_BINDINGS") as error:
        build_fixture_bundle(
            ScientificStudy.model_validate_json(json.dumps(public)), mode="confirmatory"
        )
    assert "models[" in str(error.value)
