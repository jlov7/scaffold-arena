from __future__ import annotations

import io
import json
import stat
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from artifacts_v1 import LocalArtifactStore
from persistence_v1 import ArenaRepository, create_persistence_engine
from persistence_v1.schema import metadata, study_packs
from services_v1 import ProtocolRegistryService, RegistryError


def pack_payload(*, version: str = "1.0.0") -> dict:
    return {
        "study_pack_id": "pack-one",
        "version": version,
        "title": "Synthetic Pack",
        "license_spdx": "MIT",
        "authors": [{"name": "Test"}],
        "compatibility": {"protocol_min": "1.0", "protocol_max": "1.0"},
        "allowed_claims": ["synthetic fixture exploration"],
        "limitations": ["No provider evidence."],
        "preregistration": {"reference_uri": "synthetic://pre", "content_hash": "a" * 64},
        "scenarios": [{"scenario_id": "scenario-one", "title": "Scenario", "task_family": "extract", "prompt": "Synthetic prompt."}],
        "harnesses": [{"harness_id": "harness-one", "version": "1", "adapter": "recorded"}],
        "experiments": [{
            "experiment_id": "template-one", "study_pack_id": "pack-one", "scenario_ids": ["scenario-one"],
            "harness_ids": ["harness-one"], "deterministic_weight": 0.7,
        }],
    }


def experiment_payload(*, experiment_id: str = "experiment-one", approval: str = "pending", **extra: object) -> dict:
    value = {
        "experiment_id": experiment_id,
        "study_pack_id": "pack-one",
        "scenario_ids": ["scenario-one"],
        "harness_ids": ["harness-one"],
        "deterministic_weight": 0.7,
        "owner_approval": approval,
    }
    value.update(extra)
    return value


def zipped(
    entries: list[tuple[str, bytes, int | None]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
    timestamp: tuple[int, int, int, int, int, int] = (2026, 1, 1, 0, 0, 0),
) -> bytes:
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression) as archive:
        for name, body, mode in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = compression
            info.date_time = timestamp
            if mode is not None:
                info.external_attr = mode << 16
            archive.writestr(info, body)
    return result.getvalue()


@pytest.fixture
def service(tmp_path: Path) -> ProtocolRegistryService:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    return ProtocolRegistryService(repository, LocalArtifactStore(tmp_path / "artifacts"), personal_project_id="personal")


def test_json_round_trip_import_list_and_idempotency(service: ProtocolRegistryService) -> None:
    raw = json.dumps(pack_payload()).encode()
    validated = service.validate_pack(raw, "application/json")
    assert validated["valid"] is True
    imported = service.import_pack(raw, "application/json", project_id=None)
    replay = service.import_pack(raw, "application/json", project_id=None)
    assert replay["id"] == imported["id"]
    assert replay["idempotent_replay"] is True
    assert replay["readiness"] == imported["readiness"]
    listed = service.list_packs(project_id="personal")
    assert listed[0]["study_pack_id"] == "pack-one"
    assert listed[0]["readiness"]["verdict"] == "HOLD"
    assert any(issue["code"] == "deterministic-weight" for issue in listed[0]["readiness"]["issues"])
    assert "manifest" not in listed[0]


def test_listed_legacy_pack_without_readiness_fails_closed(service: ProtocolRegistryService) -> None:
    imported = service.import_pack(json.dumps(pack_payload()).encode(), "application/json", project_id="personal")
    with service.repository.transaction() as conn:
        row = conn.execute(select(study_packs)).mappings().one()
        metadata = dict(row["content_metadata"])
        metadata.pop("readiness")
        conn.execute(
            study_packs.update()
            .where(study_packs.c.id == imported["id"])
            .values(content_metadata=metadata)
        )
    listed = service.list_packs(project_id="personal")
    assert listed[0]["readiness"]["verdict"] == "HOLD"
    assert listed[0]["readiness"]["issues"][0]["code"] == "readiness-unavailable"


def test_browser_recovery_reads_preserve_canonical_pack_and_frozen_identity(service: ProtocolRegistryService) -> None:
    service.import_pack(json.dumps(pack_payload()).encode(), "application/json", project_id="personal")
    service.create_experiment(experiment_payload(approval="approved"), project_id="personal")
    frozen = service.freeze("experiment-one", project_id="personal")

    pack = service.study_pack("pack-one", "1.0.0", project_id="personal")
    assert pack["canonical_study_pack"]["study_pack_id"] == "pack-one"
    assert pack["custody"]["artifact_integrity_verified"] is True
    assert pack["claim_ceiling"].endswith("no execution evidence")
    listed = service.list_experiments(
        project_id="personal", study_pack_id="pack-one", study_pack_version="1.0.0",
    )
    assert listed[0]["experiment_id"] == "experiment-one"
    assert "definition" not in listed[0]
    detail = service.experiment("experiment-one", project_id="personal")
    assert detail["definition"]["experiment_id"] == "experiment-one"
    assert detail["immutable_identity"]["freeze_hash"] == frozen["freeze_hash"]
    assert detail["immutable_identity"]["study_pack_hash"] == frozen["study_pack_hash"]
    assert service.list_experiments(project_id="personal", study_pack_id="pack-one", study_pack_version="missing") == []


def test_browser_recovery_registry_reads_fail_closed_for_missing_and_other_project(service: ProtocolRegistryService) -> None:
    service.import_pack(json.dumps(pack_payload()).encode(), "application/json", project_id="personal")
    service.repository.create_project("Other", project_id="other")
    with pytest.raises(RegistryError) as missing:
        service.study_pack("pack-one", "missing", project_id="personal")
    assert missing.value.status_code == 404
    with pytest.raises(RegistryError) as denied:
        service.study_pack("pack-one", "1.0.0", project_id="other")
    assert denied.value.status_code == 404
    assert service.list_experiments(project_id="other") == []


def test_zip_round_trip_and_immutable_version_conflict(service: ProtocolRegistryService) -> None:
    raw = zipped([
        ("fixtures/input.json", b'{"synthetic":true}', None),
        ("study-pack.json", json.dumps(pack_payload()).encode(), None),
    ])
    imported = service.import_pack(raw, "application/zip", project_id="personal")
    assert imported["content_digest"]
    validation = service.validate_pack(raw, "application/zip")
    assert [item["path"] for item in validation["canonical_manifest"]["files"]] == [
        "fixtures/input.json",
        "study-pack.json",
    ]
    changed = json.dumps(pack_payload(version="1.0.0") | {"title": "Different"}).encode()
    with pytest.raises(RegistryError) as error:
        service.import_pack(changed, "application/json", project_id="personal")
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    ("name", "body", "mode", "code"),
    [
        ("../study-pack.json", b"{}", None, "zip_path_unsafe"),
        ("study-pack.json", b"{}", stat.S_IFLNK | 0o777, "zip_special_entry"),
        ("payload.py", b"pass", None, "zip_executable_entry"),
        ("nested.zip", b"x", None, "zip_nested_archive"),
        ("nested.bin", b"PK\x03\x04payload", None, "zip_nested_archive"),
        ("folder/", b"", None, "zip_path_unsafe"),
        ("device", b"", stat.S_IFCHR | 0o600, "zip_special_entry"),
    ],
)
def test_malicious_archives_are_rejected(service: ProtocolRegistryService, name: str, body: bytes, mode: int | None, code: str) -> None:
    entries = [("study-pack.json", json.dumps(pack_payload()).encode(), None)] if mode is None else []
    entries.append((name, body, mode))
    raw = zipped(entries)
    result = service.validate_pack(raw, "application/zip")
    assert result["valid"] is False
    assert result["errors"][0]["code"] == code


def test_duplicate_casefold_and_ratio_bomb_are_rejected(service: ProtocolRegistryService) -> None:
    duplicate = zipped([("study-pack.json", json.dumps(pack_payload()).encode(), None), ("STUDY-PACK.JSON", b"{}", None)])
    assert service.validate_pack(duplicate, "application/zip")["errors"][0]["code"] == "zip_duplicate_path"
    bomb = zipped([("study-pack.json", b"A" * 200_000, None)])
    assert service.validate_pack(bomb, "application/zip")["errors"][0]["code"] == "zip_compression_ratio"


def test_unicode_normalized_collisions_are_rejected(service: ProtocolRegistryService) -> None:
    raw = zipped([
        ("study-pack.json", json.dumps(pack_payload()).encode(), None),
        ("fixtures/é.txt", b"one", None),
        ("fixtures/e\u0301.txt", b"two", None),
    ])
    assert service.validate_pack(raw, "application/zip")["errors"][0]["code"] == "zip_duplicate_path"


def test_repack_order_timestamp_compression_and_json_format_share_identity(service: ProtocolRegistryService) -> None:
    pretty_manifest = json.dumps(pack_payload(), indent=2).encode()
    compact_manifest = json.dumps(pack_payload(), separators=(",", ":")).encode()
    first = zipped(
        [("study-pack.json", pretty_manifest, None), ("data/fixture.txt", b"synthetic", None)],
        timestamp=(2025, 1, 1, 0, 0, 0),
    )
    second = zipped(
        [("data/fixture.txt", b"synthetic", None), ("study-pack.json", compact_manifest, None)],
        compression=zipfile.ZIP_STORED,
        timestamp=(2026, 8, 14, 12, 0, 0),
    )
    first_validation = service.validate_pack(first, "application/zip")
    second_validation = service.validate_pack(second, "application/zip")
    assert first_validation["content_digest"] == second_validation["content_digest"]
    imported = service.import_pack(first, "application/zip", project_id="personal")
    replay = service.import_pack(second, "application/zip", project_id="personal")
    assert replay["id"] == imported["id"]
    assert replay["idempotent_replay"] is True
    stored = service.artifact_store.get_bytes(imported["content_digest"])
    assert stored.startswith(b'{"files":')
    assert not stored.startswith(b"PK")

    json_validation = service.validate_pack(compact_manifest, "application/json")
    manifest_only_zip = zipped([("study-pack.json", pretty_manifest, None)])
    zip_validation = service.validate_pack(manifest_only_zip, "application/zip")
    assert json_validation["content_digest"] == zip_validation["content_digest"]


def test_service_level_body_limit_applies_to_json_and_zip(service: ProtocolRegistryService) -> None:
    limited = ProtocolRegistryService(
        service.repository,
        service.artifact_store,
        personal_project_id="personal",
        max_body_bytes=32,
    )
    with pytest.raises(RegistryError) as json_error:
        limited.validate_pack(json.dumps(pack_payload()).encode(), "application/json")
    assert json_error.value.status_code == 413
    with pytest.raises(RegistryError) as zip_error:
        limited.validate_pack(zipped([("study-pack.json", b"{}", None)]), "application/zip")
    assert zip_error.value.status_code == 413


def test_idempotent_import_re_reads_and_verifies_artifact(service: ProtocolRegistryService) -> None:
    raw = json.dumps(pack_payload()).encode()
    imported = service.import_pack(raw, "application/json", project_id="personal")
    Path(service.artifact_store.uri_for(imported["content_digest"])).write_bytes(b"tampered")
    with pytest.raises(RegistryError) as error:
        service.import_pack(raw, "application/json", project_id="personal")
    assert error.value.code == "artifact_integrity_error"


def test_create_freeze_replays_stored_definition_and_rejects_cross_pack_refs(service: ProtocolRegistryService) -> None:
    service.import_pack(json.dumps(pack_payload()).encode(), "application/json", project_id="personal")
    created = service.create_experiment(experiment_payload(approval="approved"), project_id="personal")
    frozen = service.freeze(created["experiment_id"], project_id="personal")
    assert frozen["frozen"] is True
    assert frozen["freeze_hash"]
    assert service.freeze(created["experiment_id"], project_id="personal")["idempotent_replay"] is True
    row = service._experiment_row("personal", created["experiment_id"])
    assert row is not None
    assert row["definition"]["frozen"] is True
    assert row["definition"]["freeze_hash"] == row["spec_hash"]
    with pytest.raises(RegistryError) as error:
        service.create_experiment(experiment_payload(experiment_id="different-one", scenario_ids=["missing"]), project_id="personal")
    assert error.value.code == "cross_pack_reference"


def test_preflight_holds_without_budgets_or_execution(service: ProtocolRegistryService) -> None:
    service.import_pack(json.dumps(pack_payload()).encode(), "application/json", project_id="personal")
    service.create_experiment(experiment_payload(), project_id="personal")
    report = service.preflight("experiment-one", project_id="personal")
    assert report["verdict"] == "HOLD"
    assert report["provider_execution_started"] is False
    assert {item["code"] for item in report["blockers"]} >= {
        "aggregate_budget_required",
        "experiment_not_frozen",
        "per_attempt_budget_required",
    }


def test_frozen_preflight_uses_exact_persisted_definition(service: ProtocolRegistryService) -> None:
    service.import_pack(json.dumps(pack_payload()).encode(), "application/json", project_id="personal")
    service.create_experiment(experiment_payload(approval="approved"), project_id="personal")
    service.freeze("experiment-one", project_id="personal")
    report = service.preflight("experiment-one", project_id="personal")
    assert "experiment_not_frozen" not in {item["code"] for item in report["blockers"]}
    row = service._experiment_row("personal", "experiment-one")
    assert row is not None
    mismatched = dict(row)
    mismatched["spec_hash"] = "0" * 64
    with pytest.raises(RegistryError) as error:
        service._validated_frozen_spec(mismatched)
    assert error.value.code == "frozen_state_mismatch"
    assert error.value.status_code == 409


def test_freeze_rejects_draft_race_and_preserves_newer_definition(
    service: ProtocolRegistryService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service.import_pack(json.dumps(pack_payload()).encode(), "application/json", project_id="personal")
    service.create_experiment(experiment_payload(approval="approved"), project_id="personal")
    original_freeze = service.repository.freeze_experiment

    def mutate_then_freeze(experiment_id: str, **kwargs: object) -> None:
        newer = experiment_payload(approval="approved", claim_ceiling="newer draft survives")
        service.repository.update_experiment_definition(experiment_id, newer)
        original_freeze(experiment_id, **kwargs)

    monkeypatch.setattr(service.repository, "freeze_experiment", mutate_then_freeze)
    with pytest.raises(RegistryError) as error:
        service.freeze("experiment-one", project_id="personal")
    assert error.value.status_code == 409
    row = service._experiment_row("personal", "experiment-one")
    assert row is not None
    assert row["frozen_at"] is None
    assert row["definition"]["claim_ceiling"] == "newer draft survives"


def test_predecessor_version_is_metadata_not_database_identity(service: ProtocolRegistryService) -> None:
    service.import_pack(json.dumps(pack_payload()).encode(), "application/json", project_id="personal")
    service.create_experiment(experiment_payload(experiment_id="first-one"), project_id="personal")
    created = service.create_experiment(
        experiment_payload(
            experiment_id="second-one",
            predecessor_experiment_id="first-one",
            predecessor_version="1.2.3",
        ),
        project_id="personal",
    )
    row = service._experiment_row("personal", "second-one")
    assert created["predecessor_id"] == "first-one"
    assert row is not None and row["predecessor_id"] == "first-one"


def test_missing_scenario_manipulation_check_holds_preflight(service: ProtocolRegistryService) -> None:
    payload = pack_payload()
    required_check = {"factor_id": "memory", "expected_value": True, "oracle": "memory-enabled"}
    payload["scenarios"][0]["manipulation_checks"] = [required_check]
    factor = {
        "factor_id": "memory",
        "kind": "binary",
        "levels": [False, True],
        "description": "Synthetic memory factor.",
        "treatment_mutations": [{"target": "factors.memory", "operation": "set", "level": True, "value": True}],
        "manipulation_checks": [required_check],
    }
    payload["experiments"][0]["factors"] = [factor]
    service.import_pack(json.dumps(payload).encode(), "application/json", project_id="personal")
    service.create_experiment(experiment_payload(), project_id="personal")
    report = service.preflight("experiment-one", project_id="personal")
    assert report["manipulation_checks"]["valid"] is False
    assert report["manipulation_checks"]["missing_required_checks"] == [required_check]
    assert "manipulation_checks_missing" in {item["code"] for item in report["blockers"]}
