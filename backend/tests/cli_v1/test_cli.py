from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from adapters_v1 import (
    AdapterRegistry,
    ArtifactRef,
    ProviderUsage,
    RecordedAdapter,
    ResultBundle,
)
from arena_cli.cli import main
from artifacts_v1 import LocalArtifactStore
from config.settings import Settings
from evidence_v1 import EvidenceClass, EvidenceManifest, create_receipt
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.schema import attempts, episodes, evaluations, executions, jobs
from protocol_v1 import GraderSpec, TraceEvent
from protocol_v1.canonical import canonical_json, sha256_bytes
from services_v1 import ExecutionService, ProtocolRegistryService
from tests.services_v1.test_analysis_service import _configuration
from tests.services_v1.test_analysis_service import _service as analysis_service
from tests.services_v1.test_execution_service import (
    ForbiddenAdapterRegistry,
    experiment_payload,
    pack_payload,
    provenance,
)


def _pack() -> dict:
    return {
        "study_pack_id": "pack-one",
        "version": "1.0.0",
        "title": "Synthetic Pack",
        "license_spdx": "MIT",
        "authors": [{"name": "Test"}],
        "compatibility": {"protocol_min": "1.0", "protocol_max": "1.0"},
        "allowed_claims": ["fixture only"],
        "limitations": ["synthetic"],
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
                "experiment_id": "experiment-one",
                "study_pack_id": "pack-one",
                "scenario_ids": ["scenario-one"],
                "harness_ids": ["harness-one"],
                "deterministic_weight": 0.7,
            }
        ],
    }


def _spec() -> dict:
    return {
        "experiment_id": "experiment-one",
        "study_pack_id": "pack-one",
        "scenario_ids": ["scenario-one"],
        "harness_ids": ["harness-one"],
        "deterministic_weight": 0.7,
    }


def test_help_and_module_exit_code_are_installable_and_hold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as result:
        main(["--help"])
    assert result.value.code == 0
    assert "experiment" in capsys.readouterr().out
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "arena_cli",
            "doctor",
            "--workspace",
            str(tmp_path / "missing"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 2
    assert '"verdict": "HOLD"' in process.stdout


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.1", "localhost"])
def test_personal_serve_rejects_non_loopback_binds(
    host: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["serve", "--host", host]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["code"] == "personal_bind_loopback_required"


def test_init_and_doctor_are_safe_and_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    assert main(["init", "--path", str(workspace)]) == 2
    assert not workspace.exists()
    assert main(["init", "--path", str(workspace), "--yes"]) == 0
    config = workspace / ".arena" / "config.json"
    bundled_pack = workspace / "study_packs" / "offline-demo-v1"
    assert (bundled_pack / "study-pack.json").is_file()
    assert (bundled_pack / "fixtures" / "runtime-truth-table.json").is_file()
    before = config.read_bytes()
    assert main(["doctor", "--workspace", str(workspace)]) == 0
    assert config.read_bytes() == before
    assert main(["init", "--path", str(workspace), "--yes"]) == 2
    assert "workspace_not_empty" in capsys.readouterr().out


def test_pack_validate_and_experiment_plan_are_offline_contracts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps(_pack()))
    assert main(["pack", "validate", str(pack)]) == 0
    assert '"valid": true' in capsys.readouterr().out
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}")
    assert main(["pack", "validate", str(invalid)]) == 2
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(_spec()))
    assert main(["experiment", "plan", "--spec", str(spec)]) == 0
    assert '"expected_attempts": 1' in capsys.readouterr().out


def test_xray_local_path_is_bounded_read_only_and_redacted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "harness-genome.json"
    source.write_text(
        json.dumps(
            {
                "components": [{"component_id": "memory-core", "kind": "memory"}],
                "findings": [
                    {
                        "finding_id": "inferred-one",
                        "evidence_state": "inferred",
                        "subject": "private-subject",
                        "statement": "must-not-leak",
                        "inference_basis": "captured declaration",
                    }
                ],
                "token": "must-not-leak",
            }
        )
    )
    before = source.read_bytes()
    assert main(["xray", str(source)]) == 0
    output = capsys.readouterr().out
    assert '"read_only": true' in output
    assert '"persistence": "not_persisted"' in output
    assert '"source_kind": "repository"' in output
    assert '"execution_started": false' in output
    assert "must-not-leak" not in output
    assert "private-subject" not in output
    assert source.read_bytes() == before

    oversized = tmp_path / "too-large.json"
    oversized.write_bytes(b"x" * 1_000_001)
    assert main(["xray", str(oversized)]) == 2
    held = capsys.readouterr().out
    assert '"code": "xray_path_hold"' in held
    assert oversized.stat().st_size == 1_000_001

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "harness-genome.json").write_text('{"token":"must-not-leak"}')
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".arena").symlink_to(outside, target_is_directory=True)
    assert main(["xray", str(repository)]) == 0
    assert "must-not-leak" not in capsys.readouterr().out


def test_evidence_and_export_use_real_local_contracts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    digest = store.put_bytes(b"evidence")
    manifest = EvidenceManifest(
        experiment_id="experiment-one",
        experiment_hash="a" * 64,
        study_pack_hash="b" * 64,
        spec_hash="c" * 64,
        code_hash="d" * 64,
        runtime_hash="e" * 64,
        adapter_hash="f" * 64,
        model_hash="0" * 64,
        price_hash="1" * 64,
        evaluator_hashes=("2" * 64,),
        artifact_hashes=(digest,),
        evidence_class=EvidenceClass.FIXTURE,
        claim_ceiling="fixture only",
    )
    receipt = create_receipt(manifest)
    receipt_path, manifest_path = tmp_path / "receipt.json", tmp_path / "manifest.json"
    receipt_path.write_text(receipt.model_dump_json())
    manifest_path.write_text(manifest.model_dump_json())
    assert (
        main(
            [
                "evidence",
                "verify",
                "--receipt",
                str(receipt_path),
                "--manifest",
                str(manifest_path),
                "--artifacts",
                str(tmp_path / "artifacts"),
                "--evidence-type",
                "fixture",
                "--verifier-id",
                "local-cli",
                "--verifier-digest",
                "3" * 64,
            ]
        )
        == 0
    )
    assert '"verified": true' in capsys.readouterr().out

    output = tmp_path / "existing.zip"
    output.write_bytes(b"keep")
    assert (
        main(
            [
                "export",
                "--database",
                "sqlite:///:memory:",
                "--artifacts",
                str(tmp_path / "artifacts"),
                "--project",
                "personal",
                "pack-one",
                "1.0.0",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert output.read_bytes() == b"keep"


def test_results_analyze_uses_durable_service_without_starting_workers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, execution_id = analysis_service(tmp_path)
    input_path = tmp_path / "analysis.json"
    input_path.write_text(
        json.dumps(
            {
                "experiment_id": "experiment-one",
                "execution_id": execution_id,
                "analysis_config": _configuration(),
            }
        )
    )
    result = main(
        [
            "results",
            "analyze",
            "--input",
            str(input_path),
            "--database",
            f"sqlite:///{tmp_path / 'arena.db'}",
            "--artifacts",
            str(tmp_path / "artifacts"),
            "--project",
            "personal",
        ]
    )
    assert result == 2  # truthful adequacy HOLD: one-cluster synthetic fixture
    output = capsys.readouterr().out
    assert '"report_digest"' in output and '"provider_execution_started"' not in output


def test_worker_certify_run_and_resume_fail_closed_without_runtime(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.json"
    config.write_text("{}")
    assert main(["worker", "--once"]) == 2
    assert main(["adapter", "certify", "--config", str(config)]) == 2
    config.write_text(
        json.dumps(
            {
                "harness": {
                    "harness_id": "harness-one",
                    "version": "1",
                    "adapter": "recorded",
                }
            }
        )
    )
    assert main(["worker", "--once"]) == 2
    provenance = tmp_path / "provenance.json"
    provenance.write_text("{}")
    common = [
        "--database",
        f"sqlite:///{tmp_path / 'arena.db'}",
        "--artifacts",
        str(tmp_path / "artifacts"),
        "--project",
        "personal",
    ]
    assert (
        main(
            [
                "experiment",
                "run",
                *common,
                "--idempotency-key",
                "one",
                "experiment-one",
                "--provenance",
                str(provenance),
            ]
        )
        == 2
    )
    assert main(["experiment", "resume", *common, "execution-one"]) == 2
    output = capsys.readouterr().out
    assert (
        "worker_runtime_required" in output
        and "adapter_config_invalid" in output
        and "execution_hold" in output
        and "resume_hold" in output
    )


def test_worker_rejects_runtime_arguments_instead_of_interpreting_them() -> None:
    with pytest.raises(SystemExit):
        main(["worker", "--adapter-config", "echo provider-key"])


def test_worker_healthcheck_never_leases_or_invokes_a_provider(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Runtime:
        repository = object()
        project_id = "personal"
        owner = "worker-one"
        artifact_connectivity_verified = True

        def close(self) -> None:
            self.closed = True

    runtime = Runtime()

    async def configured_runtime(_settings: Settings) -> Runtime:
        return runtime

    monkeypatch.setattr("arena_cli.cli.initialize_durable_worker_runtime", configured_runtime)
    monkeypatch.setattr("arena_cli.cli._worker_project_exists", lambda *_args: True)

    assert main(["worker", "--healthcheck"]) == 0
    assert runtime.closed is True
    assert '"provider_execution_started": false' in capsys.readouterr().out


def test_worker_rejects_unknown_project_before_claiming_any_job(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "arena.db"
    engine = create_persistence_engine(f"sqlite:///{database}")
    metadata.create_all(engine)
    ArenaRepository(engine).create_project("Personal", project_id="personal")
    config = tmp_path / "adapter-runtime.json"
    config.write_text(
        json.dumps(
            {
                "format": "scaffold-arena-adapter-runtime-v1",
                "adapters": [
                    {
                        "kind": "openai_compatible_local",
                        "adapter_id": "local-one",
                        "adapter_digest": "a" * 64,
                        "endpoint": "http://127.0.0.1:11434/v1/chat/completions",
                    }
                ],
            }
        )
    )
    settings = Settings(
        protocol_v1_database_url=f"sqlite:///{database}",
        protocol_v1_artifact_root=str(tmp_path / "artifacts"),
        protocol_v1_adapter_runtime_config=str(config),
        protocol_v1_personal_project_id="other",
    )
    monkeypatch.setattr("arena_cli.cli.Settings", lambda: settings)
    assert main(["worker", "--once"]) == 2
    assert "worker_project_mismatch" in capsys.readouterr().out


def test_worker_once_runs_attempt_then_immutable_evaluation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "arena.db"
    engine = create_persistence_engine(f"sqlite:///{database}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    store = LocalArtifactStore(tmp_path / "artifacts")
    protocol = ProtocolRegistryService(repository, store, personal_project_id="personal")
    pack = pack_payload()
    config = {"expected": {"response": "fixture"}}
    digest = GraderSpec.digest_for(
        grader_id="fixture-exact", version="1", implementation="exact_field",
        kind="deterministic", config=config,
    )
    pack["graders"] = [{
        "grader_id": "fixture-exact", "version": "1", "implementation": "exact_field",
        "kind": "deterministic", "config": config, "digest": digest,
    }]
    pack["scenarios"][0]["deterministic_metrics"] = [
        {"metric_id": "fixture", "weight": 1.0, "oracle": "fixture-exact"},
    ]
    pack["harnesses"][0]["timeout_seconds"] = 1
    protocol.import_pack(json.dumps(pack).encode(), "application/json", project_id="personal")
    protocol.create_experiment(experiment_payload(), project_id="personal")
    protocol.freeze("experiment-one", project_id="personal")
    execution_id = ExecutionService(
        repository, store, personal_project_id="personal", adapter_registry=ForbiddenAdapterRegistry(),
    ).create_execution(
        "experiment-one", provenance(), project_id="personal", request_key="cli-worker",
    )["execution_id"]
    with repository.engine.connect() as conn:
        attempt_id, episode_id = conn.execute(select(attempts.c.id, episodes.c.id).join(
            episodes, attempts.c.episode_id == episodes.c.id,
        )).one()
    output = canonical_json({"response": "fixture"})
    output_digest = sha256_bytes(output)
    adapter = RecordedAdapter(
        adapter_id="recorded-fixture",
        adapter_digest="2" * 64,
        results={
            attempt_id: ResultBundle(
                attempt_id=attempt_id, terminal_outcome="completed",
                completed_at=datetime.now(UTC) + timedelta(seconds=1),
                response_hash=output_digest, response_artifact_id="response",
                artifacts=(ArtifactRef(
                    artifact_id="response", media_type="application/json", sha256=output_digest, content=output,
                ),),
                usage=ProviderUsage(
                    evidence_source="fixture_recorded", total_tokens=1, context_tokens=1, tool_calls=0,
                ),
            ),
        },
        events={
            attempt_id: (TraceEvent(
                trace_id="trace-one", episode_id=episode_id, attempt_id=attempt_id, sequence=0,
                actor="model", event_type="response", timestamp=datetime.now(UTC),
                monotonic_time=0, payload={"fixture": True}, payload_hash="a" * 64,
            ),),
        },
    )
    registry = AdapterRegistry()
    asyncio.run(registry.install_trusted(adapter, "2" * 64))

    async def configured_registry(_location: str, **_kwargs: object) -> AdapterRegistry:
        return registry

    monkeypatch.setattr("services_v1.runtime._build_configured_adapter_registry", configured_registry)
    runtime = tmp_path / "runtime.json"
    runtime.write_text(json.dumps({
        "format": "scaffold-arena-adapter-runtime-v1",
        "adapters": [{
            "kind": "openai_compatible_local", "adapter_id": "local-unused",
            "adapter_digest": "a" * 64, "endpoint": "http://127.0.0.1:11434/v1/chat/completions",
        }],
    }))
    settings = Settings(
        protocol_v1_database_url=f"sqlite:///{database}",
        protocol_v1_artifact_root=str(tmp_path / "artifacts"),
        protocol_v1_adapter_runtime_config=str(runtime),
        protocol_v1_worker_owner="worker-one",
    )
    monkeypatch.setattr("arena_cli.cli.Settings", lambda: settings)
    assert main(["worker", "--once"]) == 0
    with repository.engine.connect() as conn:
        evaluation = conn.execute(select(evaluations).where(evaluations.c.attempt_id == attempt_id)).mappings().one()
        execution = conn.execute(select(executions).where(executions.c.id == execution_id)).mappings().one()
        statuses = conn.execute(select(jobs.c.kind, jobs.c.status).where(jobs.c.execution_id == execution_id)).all()
    assert evaluation["result_artifact_digest"]
    assert execution["status"] == "completed"
    assert dict(statuses) == {"attempt": "completed", "evaluation": "completed"}
    assert '"provider_execution_started": true' in capsys.readouterr().out
