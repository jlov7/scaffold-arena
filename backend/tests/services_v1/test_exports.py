from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from artifacts_v1 import LocalArtifactStore
from persistence_v1 import ArenaRepository, create_persistence_engine
from persistence_v1.schema import metadata
from services_v1 import ExportError, ProtocolRegistryService, StudyPackExportService
from services_v1.exports import _analysis_content


def pack_payload() -> dict:
    return {
        "study_pack_id": "pack-one",
        "version": "1.0.0",
        "title": "Synthetic Pack",
        "license_spdx": "MIT",
        "authors": [{"name": "Test"}],
        "compatibility": {"protocol_min": "1.0", "protocol_max": "1.0"},
        "allowed_claims": ["synthetic fixture exploration"],
        "limitations": ["No provider evidence."],
        "preregistration": {
            "reference_uri": "synthetic://pre",
            "content_hash": "a" * 64,
        },
        "scenarios": [
            {
                "scenario_id": "scenario-one",
                "title": "Scenario",
                "task_family": "extract",
                "prompt": "Synthetic prompt.",
            }
        ],
        "harnesses": [
            {"harness_id": "harness-one", "version": "1", "adapter": "recorded"}
        ],
        "experiments": [
            {
                "experiment_id": "template-one",
                "study_pack_id": "pack-one",
                "scenario_ids": ["scenario-one"],
                "harness_ids": ["harness-one"],
                "deterministic_weight": 0.7,
            }
        ],
    }


def pack_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("fixtures/input.json", b'{"synthetic":true}')
        archive.writestr("study-pack.json", json.dumps(pack_payload(), indent=2))
    return output.getvalue()


@pytest.fixture
def services(tmp_path: Path) -> tuple[ProtocolRegistryService, StudyPackExportService]:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    repository.create_project("Other", project_id="other")
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    registry = ProtocolRegistryService(
        repository, artifacts, personal_project_id="personal"
    )
    registry.import_pack(pack_zip(), "application/zip", project_id="personal")
    return registry, StudyPackExportService(
        repository, artifacts, personal_project_id="personal"
    )


def test_export_is_canonical_idempotent_and_round_trips_without_content_change(
    services: tuple[ProtocolRegistryService, StudyPackExportService],
    tmp_path: Path,
) -> None:
    registry, exporter = services
    first = exporter.export_study_pack("pack-one", "1.0.0", project_id="personal")
    second = exporter.export_study_pack("pack-one", "1.0.0", project_id="personal")
    assert first.content == second.content
    assert first.manifest_hash == second.manifest_hash
    assert first.content.startswith(b"PK")
    validated = registry.validate_pack(first.content, "application/zip")
    assert validated["valid"] is True
    assert validated["manifest_hash"] == first.manifest_hash
    assert validated["content_digest"] == first.content_digest

    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'round-trip.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Second", project_id="second")
    second_registry = ProtocolRegistryService(
        repository,
        LocalArtifactStore(tmp_path / "round-trip-artifacts"),
        personal_project_id="second",
    )
    imported = second_registry.import_pack(
        first.content, "application/zip", project_id="second"
    )
    replay_exporter = StudyPackExportService(
        repository, second_registry.artifact_store, personal_project_id="second"
    )
    replay = replay_exporter.export_study_pack("pack-one", "1.0.0", project_id="second")
    assert imported["manifest_hash"] == first.manifest_hash
    assert imported["content_digest"] == first.content_digest
    assert replay.content == first.content
    assert replay.manifest_hash == first.manifest_hash


def test_export_denies_cross_project_access(
    services: tuple[ProtocolRegistryService, StudyPackExportService],
) -> None:
    _, exporter = services
    with pytest.raises(ExportError) as error:
        exporter.export_study_pack("pack-one", "1.0.0", project_id="other")
    assert error.value.code == "study_pack_not_found"
    assert error.value.status_code == 404


def test_export_fails_closed_when_artifact_is_missing_or_corrupt(
    services: tuple[ProtocolRegistryService, StudyPackExportService],
) -> None:
    registry, exporter = services
    imported = registry.list_packs(project_id="personal")[0]
    artifact_path = Path(registry.artifact_store.uri_for(imported["content_digest"]))
    artifact_path.write_bytes(b"corrupt")
    with pytest.raises(ExportError) as error:
        exporter.export_study_pack("pack-one", "1.0.0", project_id="personal")
    assert error.value.code == "artifact_unavailable"
    assert error.value.status_code == 409


def test_export_rejects_a_hash_mismatched_artifact(
    services: tuple[ProtocolRegistryService, StudyPackExportService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, exporter = services
    monkeypatch.setattr(
        registry.artifact_store, "get_bytes", lambda _digest: b"unverified"
    )
    with pytest.raises(ExportError) as error:
        exporter.export_study_pack("pack-one", "1.0.0", project_id="personal")
    assert error.value.code == "artifact_integrity_error"
    assert error.value.status_code == 409


def test_export_rejects_secret_fields_in_registered_declarative_pack(
    tmp_path: Path,
) -> None:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'secret.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    artifacts = LocalArtifactStore(tmp_path / "secret-artifacts")
    registry = ProtocolRegistryService(
        repository, artifacts, personal_project_id="personal"
    )
    payload = pack_payload()
    payload["harnesses"][0]["configuration"] = {"api_key": "must-not-export"}
    from protocol_v1 import canonical_configuration_hash

    payload["harnesses"][0]["effective_configuration_hash"] = (
        canonical_configuration_hash(payload["harnesses"][0]["configuration"])
    )
    registry.import_pack(
        json.dumps(payload).encode(), "application/json", project_id="personal"
    )
    exporter = StudyPackExportService(
        repository, artifacts, personal_project_id="personal"
    )
    with pytest.raises(ExportError) as error:
        exporter.export_study_pack("pack-one", "1.0.0", project_id="personal")
    assert error.value.code == "secret_field_present"


def test_analysis_csv_neutralizes_formula_leading_text_cells() -> None:
    content, media_type, suffix = _analysis_content(
        [{
            "report_digest": "a" * 64,
            "record_type": "main",
            "record_id": "=HYPERLINK(\"https://attacker.invalid\")",
            "outcome": "\t+1+1",
            "status": "ESTIMATED",
            "estimate": "-0.5",
            "ci_low": "-1.0",
            "ci_high": "0.0",
            "attempt_ids": "@SUM(1,1)",
            "constituent_attempt_ids": " -1+1",
        }],
        "csv",
    )

    assert media_type == "text/csv; charset=utf-8"
    assert suffix == "csv"
    row = next(__import__("csv").DictReader(io.StringIO(content.decode())))
    assert row["record_id"].startswith("'")
    assert row["outcome"].startswith("'")
    assert row["attempt_ids"].startswith("'")
    assert row["constituent_attempt_ids"].startswith("'")
    assert row["estimate"] == "-0.5"
