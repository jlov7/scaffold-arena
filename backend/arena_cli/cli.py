"""Argparse CLI that calls protocol contracts and never starts providers implicitly."""

from __future__ import annotations

import argparse
import asyncio
import difflib
import hashlib
import ipaddress
import json
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from adapters_v1 import AttemptInput, certify_adapter
from adapters_v1.offline_fixture import bundled_study_pack_root
from arena_cli.demo import DemoWorkspaceError, run_demo
from arena_cli.provenance import collect_study_pack_provenance
from artifacts_v1 import LocalArtifactStore
from config.settings import Settings
from evidence_v1 import EvidenceManifest, EvidenceReceipt, verify_evidence
from forge_v1 import ForgeProposal
from persistence_v1 import ArenaRepository, create_persistence_engine
from persistence_v1.schema import projects
from protocol_v1 import ExperimentSpec, HarnessSpec, expand_design
from protocol_v1.canonical import canonical_json
from services_v1 import (
    AnalysisError,
    AnalysisExportService,
    AnalysisService,
    CounterfactualReplayService,
    DecisionError,
    DecisionService,
    ExecutionError,
    ExecutionService,
    ExperimentPlannerService,
    ExportError,
    HarnessCIService,
    ProcessSafetyService,
    ProtocolRegistryService,
    ProtocolRuntimeConfigurationError,
    RegistryError,
    StudyPackExportService,
    XrayError,
    XrayService,
    build_adapter_registry_from_config,
    initialize_durable_worker_runtime,
)
from services_v1.offline_demo_runtime import enable_local_offline_demo_capability

_HOLD = 2
_CONFIG = ".arena/config.json"
_XRAY_MAX_SOURCE_BYTES = 1_000_000
_XRAY_MAX_DIRECTORY_ENTRIES = 1_024
_XRAY_IGNORED_DIRECTORIES = frozenset({".git", ".venv", "node_modules", "__pycache__", "build", "dist", "coverage"})
_XRAY_DESCRIPTOR_CANDIDATES = ("harness-genome.json", "genome.json", "scaffold-arena.json", ".arena/harness-genome.json")


def _emit(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, default=str, sort_keys=True))


def _hold(code: str, prerequisite: str) -> int:
    _emit({"verdict": "HOLD", "code": code, "prerequisite": prerequisite})
    return _HOLD


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def _repository(database: str) -> ArenaRepository:
    return ArenaRepository(create_persistence_engine(database))


def _media_type(path: Path) -> str:
    return "application/zip" if path.suffix.lower() == ".zip" else "application/json"


def command_init(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        return _hold(
            "workspace_not_empty",
            "Choose an empty directory; init never overwrites an existing workspace.",
        )
    if not args.yes:
        return _hold(
            "confirmation_required",
            "Re-run `arena init --yes` after choosing the empty workspace path.",
        )
    root.mkdir(parents=True, exist_ok=True)
    config = root / _CONFIG
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps({"format": "scaffold-arena-workspace-v1"}, indent=2) + "\n"
    )
    bundled_pack = root / "study_packs" / "offline-demo-v1"
    shutil.copytree(bundled_study_pack_root(), bundled_pack)
    _emit(
        {
            "verdict": "PASS",
            "workspace": str(root.resolve()),
            "config": str(config.resolve()),
            "bundled_study_pack": str(bundled_pack.resolve()),
            "provider_execution_started": False,
        }
    )
    return 0


def command_demo(args: argparse.Namespace) -> int:
    try:
        result = run_demo(args.path)
    except DemoWorkspaceError as exc:
        if str(exc) == "workspace_not_empty":
            return _hold(
                "workspace_not_empty",
                "Choose an empty directory; demo never overwrites an existing workspace.",
            )
        return _hold(
            "demo_fixture_hold",
            "The bundled fixture, StudyPack, provenance capture, or descriptive summary could not be verified.",
        )
    except (OSError, TypeError, ValueError):
        return _hold(
            "demo_fixture_hold",
            "The bundled fixture, StudyPack, provenance capture, or descriptive summary could not be verified.",
        )
    _emit(result)
    return 0


def command_provenance_capture(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser()
    if output.exists():
        return _hold(
            "provenance_target_exists",
            "Choose a new output path; provenance capture never overwrites evidence.",
        )
    try:
        captured = collect_study_pack_provenance(
            repository_root=Path(args.root),
            study_pack_path=Path(args.study_pack),
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = captured.model_dump(mode="json")
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError):
        return _hold(
            "provenance_capture_hold",
            "Provide a readable repository root, strict StudyPack JSON, and new writable output path.",
        )
    _emit(
        {
            "verdict": "PASS",
            "provider_execution_started": False,
            "output": str(output.resolve()),
            **payload,
        }
    )
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    root = Path(args.workspace).expanduser()
    config = root / _CONFIG
    if not config.is_file():
        return _hold(
            "workspace_not_initialized",
            "Run `arena init --yes --path <empty-directory>`; doctor is read-only.",
        )
    try:
        value = _json(config)
    except (TypeError, ValueError):
        return _hold(
            "workspace_config_invalid",
            "Repair the existing .arena/config.json; doctor will not modify it.",
        )
    if value.get("format") != "scaffold-arena-workspace-v1":
        return _hold(
            "workspace_format_unknown",
            "Use a Scaffold Arena v1 workspace configuration.",
        )
    _emit(
        {
            "verdict": "PASS",
            "workspace": str(root.resolve()),
            "read_only": True,
            "provider_execution_started": False,
        }
    )
    return 0


def command_pack_validate(args: argparse.Namespace) -> int:
    path = Path(args.pack)
    try:
        raw = path.read_bytes()
    except OSError:
        return _hold(
            "pack_unreadable", "Provide a readable JSON or ZIP StudyPack file."
        )
    service = ProtocolRegistryService(
        _repository("sqlite:///:memory:"), _UnavailableStore()
    )
    result = service.validate_pack(raw, _media_type(path))
    _emit(result)
    return 0 if result["valid"] else _HOLD


def command_experiment_plan(args: argparse.Namespace) -> int:
    try:
        spec = ExperimentSpec.model_validate_json(json.dumps(_json(Path(args.spec))))
        treatments = expand_design(spec)
    except (ValueError, TypeError):
        return _hold(
            "experiment_spec_invalid",
            "Provide a valid protocol-v1 ExperimentSpec JSON file.",
        )
    expected = (
        len(treatments)
        * len(spec.scenario_ids)
        * len(spec.harness_ids)
        * max(len(spec.model_endpoints), 1)
        * spec.repetitions
    )
    _emit(
        {
            "verdict": "PASS",
            "experiment_id": spec.experiment_id,
            "design_expansion_count": len(treatments),
            "expected_attempts": expected,
            "provider_execution_started": False,
        }
    )
    return 0


def command_experiment_preflight(args: argparse.Namespace) -> int:
    try:
        service = ProtocolRegistryService(
            _repository(args.database),
            LocalArtifactStore(args.artifacts),
            personal_project_id=args.project,
        )
        report = service.preflight(args.experiment_id, project_id=args.project)
    except (OSError, RegistryError, SQLAlchemyError, ValueError):
        return _hold(
            "preflight_unavailable",
            "Provide an initialized database, artifact store, project, and registered experiment.",
        )
    _emit(report)
    return 0 if report["verdict"] == "PASS" else _HOLD


def command_experiment_run(args: argparse.Namespace) -> int:
    try:
        provenance = _json(Path(args.provenance))
        service = ExecutionService(
            _repository(args.database),
            LocalArtifactStore(args.artifacts),
            personal_project_id=args.project,
        )
        result = service.create_execution(
            args.experiment_id,
            provenance,
            project_id=args.project,
            request_key=args.idempotency_key,
        )
    except (ExecutionError, OSError, SQLAlchemyError, ValueError):
        return _hold(
            "execution_hold",
            "Provide approved frozen fixture-only protocol inputs and all durable execution prerequisites.",
        )
    _emit(result)
    return 0


def command_experiment_resume(args: argparse.Namespace) -> int:
    try:
        service = ExecutionService(
            _repository(args.database),
            LocalArtifactStore(args.artifacts),
            personal_project_id=args.project,
        )
        result = service.resume(args.execution_id, project_id=args.project)
    except (ExecutionError, OSError, SQLAlchemyError, ValueError):
        return _hold(
            "resume_hold",
            "Inject a checkpoint-capable durable resume worker through the application runtime; CLI never creates one.",
        )
    _emit(result)
    return 0


def _bounded_xray_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("X-Ray accepts a regular file, not a symlink or device")
    with path.open("rb") as handle:
        data = handle.read(_XRAY_MAX_SOURCE_BYTES + 1)
    if len(data) > _XRAY_MAX_SOURCE_BYTES:
        raise ValueError("X-Ray source exceeds its static byte bound")
    return data


def _xray_path_snapshot(path: Path) -> bytes:
    if path.is_symlink():
        raise ValueError("X-Ray rejects symlink targets")
    target = path.resolve(strict=True)
    if target.is_file():
        return _bounded_xray_file(target)
    if not target.is_dir():
        raise ValueError("X-Ray target must be a regular file or directory")
    entries: list[dict[str, int | str]] = []
    for root, directories, files in os.walk(target, followlinks=False):
        directories[:] = sorted(directory for directory in directories if directory not in _XRAY_IGNORED_DIRECTORIES and not (Path(root) / directory).is_symlink())
        for filename in sorted(files):
            candidate = Path(root) / filename
            if candidate.is_symlink() or not candidate.is_file():
                continue
            relative = candidate.relative_to(target).as_posix()
            entries.append({"path_digest": hashlib.sha256(relative.encode("utf-8")).hexdigest(), "size_bytes": candidate.stat().st_size})
            if len(entries) >= _XRAY_MAX_DIRECTORY_ENTRIES:
                break
        if len(entries) >= _XRAY_MAX_DIRECTORY_ENTRIES:
            break
    structured: dict[str, Any] | None = None
    for relative in _XRAY_DESCRIPTOR_CANDIDATES:
        candidate = target / relative
        if not candidate.exists() or candidate.is_symlink() or not candidate.is_file():
            continue
        resolved_candidate = candidate.resolve(strict=True)
        if target not in (resolved_candidate, *resolved_candidate.parents):
            continue
        try:
            parsed = json.loads(_bounded_xray_file(resolved_candidate))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError):
            continue
        if isinstance(parsed, dict):
            structured = parsed
            break
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return json.dumps(
        {
            "schema": "scaffold-arena.xray.repository-manifest/1",
            "entry_count": len(entries),
            "truncated": len(entries) == _XRAY_MAX_DIRECTORY_ENTRIES,
            "entries": entries,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _local_xray_report(path: str, *, source_kind: str, profile_id: str | None) -> dict[str, Any]:
    source = _xray_path_snapshot(Path(path).expanduser())
    source_digest = hashlib.sha256(source).hexdigest()
    report = XrayService._build_report(
        source,
        source_digest=source_digest,
        source_kind=source_kind,
        profile_id=profile_id,
    )
    raw = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    report_digest = hashlib.sha256(raw).hexdigest()
    return {
        **report,
        "report_id": f"xray-{report_digest[:24]}",
        "report_digest": f"sha256:{report_digest}",
        "analysis_digest": f"sha256:{report_digest}",
        "persistence": "not_persisted",
        "read_only": True,
        "provider_execution_started": False,
        "execution_started": False,
        "network_requested": False,
    }


def command_xray(args: argparse.Namespace) -> int:
    """Inspect an explicit local path or an existing artifact; neither mode executes it."""
    if args.path:
        if args.source_artifact_digest:
            return _hold("xray_input_ambiguous", "Use either an explicit local path or --source-artifact-digest, never both.")
        try:
            _emit(
                _local_xray_report(
                    args.path,
                    source_kind=(
                        "repository" if args.source_kind == "auto" else args.source_kind
                    ),
                    profile_id=args.profile_id,
                )
            )
            return 0
        except (OSError, TypeError, ValueError):
            return _hold("xray_path_hold", "Provide a readable regular file or bounded directory. X-Ray reads static bytes only and never executes, installs, or fetches a target.")
    if not args.source_artifact_digest or not args.database or not args.artifacts or not args.project:
        return _hold("xray_artifact_context_required", "Use `arena xray <path>` for read-only local inspection, or provide --source-artifact-digest with --database, --artifacts, and --project for a durable report.")
    try:
        result = XrayService(
            _repository(args.database),
            LocalArtifactStore(args.artifacts),
            personal_project_id=args.project,
        ).create_report(
            {
                "source_artifact_digest": args.source_artifact_digest,
                "source_kind": args.source_kind,
                **({"profile_id": args.profile_id} if args.profile_id else {}),
            },
            project_id=args.project,
        )
    except (XrayError, OSError, SQLAlchemyError, ValueError):
        return _hold(
            "xray_hold",
            "Provide an existing project-visible captured artifact and a supported static source kind; arena xray never executes source or requests a network resource.",
        )
    _emit(result)
    return 0


def _write_cli_artifact(path_value: str, contents: str, *, append: bool = False) -> None:
    path = Path(path_value).expanduser()
    if path.exists() and not append:
        raise ValueError("output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    if append:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(contents)
            if not contents.endswith("\n"):
                handle.write("\n")
        return
    path.write_text(contents + ("" if contents.endswith("\n") else "\n"), encoding="utf-8")


def _counterfactual_local_service() -> CounterfactualReplayService:
    # local_report intentionally reads no persistence or artifact store state.
    return CounterfactualReplayService(None, None)  # type: ignore[arg-type]


def _planner_local_service() -> ExperimentPlannerService:
    # local_report is a pure design simulation and intentionally reads no runtime state.
    return ExperimentPlannerService(None, None)  # type: ignore[arg-type]


def _process_safety_local_service() -> ProcessSafetyService:
    # local_report only verifies a caller-supplied digest/redacted-manifest contract.
    return ProcessSafetyService(None, None)  # type: ignore[arg-type]


def command_forge_proposal(args: argparse.Namespace) -> int:
    try:
        proposal = ForgeProposal.model_validate(_json(Path(args.input)))
        digest = hashlib.sha256(canonical_json(proposal)).hexdigest()
        result = {
            "verdict": "HOLD",
            "proposal_id": proposal.proposal_id,
            "proposal_digest": f"sha256:{digest}",
            "state": "PENDING_APPROVAL",
            "untrusted": True,
            "execution_started": False,
            "automatic_merge": False,
            "prerequisite": "Submit the digest-bound proposal through a project-scoped Forge service for independent owner or policy approval; this CLI cannot approve, evaluate, execute, or merge it.",
        }
        if args.output:
            _write_cli_artifact(args.output, json.dumps(result, indent=2, sort_keys=True))
    except (OSError, TypeError, ValueError):
        return _hold("forge_proposal_hold", "Provide a strict untrusted proposal with exactly one digest-bound mechanism change, falsifiable prediction, rollback identity, and bounded claim scope.")
    _emit(result)
    return _HOLD


def command_forge_plan(args: argparse.Namespace) -> int:
    try:
        report = _planner_local_service().local_report(_json(Path(args.input)))
        if args.output:
            _write_cli_artifact(args.output, json.dumps(report, indent=2, sort_keys=True))
    except (OSError, TypeError, ValueError):
        return _hold("forge_planner_hold", "Provide a strict budget- and risk-constrained planner request with declared uncertainty, mechanisms, coverage, evidence, cost, risk, MDE, and remaining budget.")
    _emit(report)
    return 0 if report["verdict"] == "READY" else _HOLD


def command_forge_process_safety(args: argparse.Namespace) -> int:
    try:
        report = _process_safety_local_service().local_report(_json(Path(args.input)))
        if args.output:
            _write_cli_artifact(args.output, json.dumps(report, indent=2, sort_keys=True))
    except (OSError, TypeError, ValueError):
        return _hold("process_safety_hold", "Provide a strict digest-only process-safety contract with all typed outcomes, flow labels, policy, state transitions, and cleanup receipt.")
    _emit(report)
    return {"PASS": 0, "HOLD": _HOLD, "FAIL": 1}[report["verdict"]]


def command_forge_evaluate_hold(_: argparse.Namespace) -> int:
    return _hold("forge_evaluation_service_required", "Evaluation needs a project-scoped immutable proposal, independent owner approval, sealed-runner custody, a PASS process-safety report, and a distinct evaluator/admitter. This public CLI never self-grades, promotes, executes, or merges.")


def command_counterfactual_replay(args: argparse.Namespace) -> int:
    try:
        payload = _json(Path(args.input))
        if payload.get("mode") == "live" and not args.live:
            return _hold("live_flag_required", "Use --live with an explicit credentials attestation, budget, and policy digest; this CLI still will not start a provider.")
        if args.live:
            if not args.credentials_configured or args.budget_usd is None or not args.live_policy_digest:
                return _hold("live_authorization_required", "Live declarations require --credentials-configured, --budget-usd, and --live-policy-digest. No credential material is accepted.")
            payload["mode"] = "live"
            payload["live_authorization"] = {"credentials_configured": True, "budget_usd": args.budget_usd, "policy_digest": args.live_policy_digest}
        report = _counterfactual_local_service().local_report(payload)
        if args.output:
            _write_cli_artifact(args.output, json.dumps(report, indent=2, sort_keys=True))
    except (OSError, TypeError, ValueError):
        return _hold("counterfactual_replay_hold", "Provide a strict replay contract with one intervention, common checkpoint/environment bindings, disjoint cohorts, and recorded branch references.")
    _emit(report)
    return {"PASS": 0, "HOLD": _HOLD, "FAIL": 1}[report["verdict"]]


def _bounded_diff(base: Path, candidate: Path) -> tuple[str, str, str]:
    if base.is_symlink() or candidate.is_symlink() or not base.is_file() or not candidate.is_file():
        raise ValueError("base and candidate must be regular files")
    base_bytes, candidate_bytes = base.read_bytes(), candidate.read_bytes()
    if len(base_bytes) > 1_000_000 or len(candidate_bytes) > 1_000_000:
        raise ValueError("base and candidate must remain under one megabyte")
    base_text, candidate_text = base_bytes.decode("utf-8"), candidate_bytes.decode("utf-8")
    diff = "".join(difflib.unified_diff(base_text.splitlines(keepends=True), candidate_text.splitlines(keepends=True), fromfile="base", tofile="candidate"))[:32_768]
    return hashlib.sha256(base_bytes).hexdigest(), hashlib.sha256(candidate_bytes).hexdigest(), diff or "# no textual diff available\n"


def command_harness_ci(args: argparse.Namespace) -> int:
    try:
        replay_payload = _json(Path(args.replay))
        policy = _json(Path(args.policy))
        base_digest, candidate_digest, diff = _bounded_diff(Path(args.base), Path(args.candidate))
        ci = HarnessCIService(None, None, replay_service=_counterfactual_local_service())  # type: ignore[arg-type]
        report = ci.local_report(replay_payload, {
            "base_source_digest": f"sha256:{base_digest}",
            "candidate_source_digest": f"sha256:{candidate_digest}",
            "source_changes": [{"path": "base-vs-candidate.diff", "diff_text": diff}],
            "policy": policy,
        })
        summary_path = args.summary or os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            _write_cli_artifact(summary_path, report["step_summary"], append=True)
        if args.comment_output:
            _write_cli_artifact(args.comment_output, report["pr_comment_body"])
        if args.output:
            _write_cli_artifact(args.output, json.dumps(report, indent=2, sort_keys=True))
    except (OSError, TypeError, ValueError):
        return _hold("harness_ci_hold", "Provide readable base/candidate files, a strict replay contract, and a strict Harness CI policy. The CLI never starts a provider.")
    _emit(report)
    return {"PASS": 0, "HOLD": _HOLD, "FAIL": 1}[report["verdict"]]


def command_adapter_certify(args: argparse.Namespace) -> int:
    try:
        config = _json(Path(args.config))
        HarnessSpec.model_validate_json(json.dumps(config["harness"]))
        input = AttemptInput.model_validate_json(json.dumps(config["attempt_input"]))
        runtime = config["runtime"]
        if not isinstance(runtime, dict):
            raise TypeError("runtime must be an object")
        registry = asyncio.run(build_adapter_registry_from_config(runtime))
        harness = HarnessSpec.model_validate_json(json.dumps(config["harness"]))
        adapter = registry.get(
            harness.adapter_identity or "", harness.adapter_digest or ""
        )
    except (KeyError, ProtocolRuntimeConfigurationError, ValueError, TypeError):
        return _hold(
            "adapter_config_invalid",
            "Provide runtime, harness, and complete attempt_input bindings in --config.",
        )
    report = asyncio.run(certify_adapter(adapter, harness, input))
    _emit(report.model_dump(mode="json"))
    return 0 if report.passed else _HOLD


def command_worker(args: argparse.Namespace) -> int:
    return asyncio.run(_run_configured_worker(args))


async def _run_configured_worker(args: argparse.Namespace) -> int:
    """Run only the fixed settings-owned worker process contract."""
    try:
        runtime = await initialize_durable_worker_runtime(Settings())
    except ProtocolRuntimeConfigurationError:
        return _hold(
            "worker_runtime_required",
            "Configure the fixed worker settings, durable database, trusted adapter registry, and artifact store.",
        )
    try:
        if args.once:
            if not _worker_project_exists(runtime.repository, runtime.project_id):
                return _hold(
                    "worker_project_mismatch",
                    "The configured worker project is unavailable.",
                )
            result = await runtime.worker.run_once(runtime.owner, lease_seconds=runtime.lease_seconds)
            evaluation = runtime.evaluator.run_once(runtime.owner, lease_seconds=runtime.lease_seconds)
            _emit(
                {
                    "verdict": "PASS",
                    "worker": runtime.owner,
                    "result": result.__dict__ if result else None,
                    "evaluation": evaluation.__dict__ if evaluation else None,
                    "provider_execution_started": result is not None,
                }
            )
            return 0
        if args.healthcheck:
            if not _worker_project_exists(runtime.repository, runtime.project_id):
                return _hold(
                    "worker_project_mismatch",
                    "The configured worker project is unavailable.",
                )
            _emit(
                {
                    "verdict": "PASS",
                    "worker": runtime.owner,
                    "database": "connected",
                    "artifact_connectivity_verified": runtime.artifact_connectivity_verified,
                    "provider_execution_started": False,
                }
            )
            return 0
        try:
            while True:
                if not _worker_project_exists(runtime.repository, runtime.project_id):
                    return _hold(
                        "worker_project_mismatch",
                        "The configured worker project is unavailable.",
                    )
                result = await runtime.worker.run_once(
                    runtime.owner, lease_seconds=runtime.lease_seconds
                )
                evaluation = runtime.evaluator.run_once(
                    runtime.owner, lease_seconds=runtime.lease_seconds
                )
                if result is not None or evaluation is not None:
                    _emit(
                        {
                            "verdict": "PASS",
                            "worker": runtime.owner,
                            "result": result.__dict__ if result else None,
                            "evaluation": evaluation.__dict__ if evaluation else None,
                        }
                    )
                await asyncio.sleep(runtime.poll_seconds)
        except KeyboardInterrupt:
            return 0
    except SQLAlchemyError:
        return _hold(
            "worker_project_mismatch",
            "The configured database cannot verify the requested durable project.",
        )
    finally:
        runtime.close()


def _worker_project_exists(repository: ArenaRepository, project_id: str) -> bool:
    with repository.engine.connect() as connection:
        return connection.execute(
            select(projects.c.id).where(projects.c.id == project_id)
        ).scalar_one_or_none() is not None


def command_results_analyze(args: argparse.Namespace) -> int:
    try:
        payload = _json(Path(args.input))
        result = AnalysisService(
            _repository(args.database),
            LocalArtifactStore(args.artifacts),
            personal_project_id=args.project,
        ).analyze(payload, project_id=args.project)
    except (AnalysisError, OSError, SQLAlchemyError, ValueError):
        return _hold(
            "analysis_hold",
            "Provide project-scoped IDs and the exact preregistered configuration; all outcome, trace, evaluator, and cost evidence is loaded from durable records.",
        )
    _emit(result)
    return 0 if result["verdict"] == "PASS" else _HOLD


def command_results_brief(args: argparse.Namespace) -> int:
    try:
        payload = _json(Path(args.input))
        result = DecisionService(
            _repository(args.database),
            LocalArtifactStore(args.artifacts),
            personal_project_id=args.project,
        ).create(payload, project_id=args.project)
    except (DecisionError, OSError, SQLAlchemyError, ValueError):
        return _hold(
            "decision_hold",
            "Provide only project-scoped analysis identifiers, risk constraints, and proposed claims linked by durable receipt IDs; this command starts no provider.",
        )
    _emit({**result, "provider_execution_started": False})
    return 0 if result["verdict"] == "PASS" else _HOLD


def command_results_export(args: argparse.Namespace) -> int:
    target = Path(args.output)
    if target.exists():
        return _hold("export_target_exists", "Choose a new output path; export will not overwrite artifacts.")
    try:
        exported = AnalysisExportService(
            _repository(args.database), LocalArtifactStore(args.artifacts), personal_project_id=args.project,
        ).export_analysis(args.report_digest, args.format, project_id=args.project)
        target.write_bytes(exported.content)
    except (ExportError, OSError, SQLAlchemyError, ValueError):
        return _hold("analysis_export_hold", "Provide a project-bound immutable analysis report; Parquet also requires the research optional dependency group.")
    _emit({"verdict": "PASS", "output": str(target), "report_digest": exported.report_digest, "manifest_hash": exported.manifest_hash, "export_digest": exported.export_digest})
    return 0


def command_evidence_verify(args: argparse.Namespace) -> int:
    try:
        receipt = EvidenceReceipt.model_validate_json(Path(args.receipt).read_text())
        manifest = EvidenceManifest.model_validate_json(Path(args.manifest).read_text())
        result = verify_evidence(
            receipt,
            manifest,
            LocalArtifactStore(args.artifacts),
            evidence_type=args.evidence_type,
            verifier_id=args.verifier_id,
            verifier_digest=args.verifier_digest,
        )
    except (OSError, ValueError, TypeError):
        return _hold(
            "evidence_input_invalid",
            "Provide valid receipt, manifest, local artifact store, and verifier identity/digest.",
        )
    _emit(result.model_dump(mode="json"))
    return 0 if result.verified else _HOLD


def command_export(args: argparse.Namespace) -> int:
    target = Path(args.output)
    if target.exists():
        return _hold(
            "export_target_exists",
            "Choose a new output path; export will not overwrite artifacts.",
        )
    try:
        exported = StudyPackExportService(
            _repository(args.database),
            LocalArtifactStore(args.artifacts),
            personal_project_id=args.project,
        ).export_study_pack(args.study_pack_id, args.version, project_id=args.project)
        target.write_bytes(exported.content)
    except (ExportError, OSError, SQLAlchemyError, ValueError):
        return _hold(
            "export_hold",
            "Provide a registered, verified StudyPack and a new writable output path.",
        )
    _emit(
        {
            "verdict": "PASS",
            "output": str(target),
            "export_digest": exported.export_digest,
            "claim_ceiling": "portable declarative StudyPack only",
        }
    )
    return 0


def command_serve(args: argparse.Namespace) -> int:
    settings = Settings()
    if (
        not settings.protocol_v1_is_team_mode
        and not _is_literal_loopback_host(args.host)
    ):
        return _hold(
            "personal_bind_loopback_required",
            "Personal mode may serve only on a literal loopback address; use team mode for a non-loopback bind.",
        )
    if args.enable_offline_demo:
        if settings.protocol_v1_is_team_mode:
            return _hold(
                "offline_demo_personal_local_only",
                "The bundled offline demonstration is available only from the personal local workbench.",
            )
        # This is a startup capability, not a request-header convention.  The
        # command has already rejected non-literal loopback personal binds.
        enable_local_offline_demo_capability()
    import uvicorn

    uvicorn.run("main:app", host=args.host, port=args.port, proxy_headers=False)
    return 0


def _is_literal_loopback_host(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _UnavailableStore:
    def get_bytes(self, digest: str) -> bytes:
        raise FileNotFoundError(digest)


def _add_database_arguments(
    parser: argparse.ArgumentParser, *, execution: bool = False
) -> None:
    parser.add_argument("--database", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--project", required=True)
    if execution:
        parser.add_argument("--idempotency-key", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arena", description="Scaffold Arena protocol-v1 control CLI"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--path", default=".")
    init.add_argument("--yes", action="store_true")
    init.set_defaults(handler=command_init)
    demo = commands.add_parser("demo")
    demo.add_argument("--path", default="scaffold-arena-demo")
    demo.set_defaults(handler=command_demo)
    provenance = commands.add_parser("provenance")
    provenance_sub = provenance.add_subparsers(dest="provenance_command", required=True)
    capture = provenance_sub.add_parser("capture")
    capture.add_argument("--root", default=".")
    capture.add_argument("--study-pack", required=True)
    capture.add_argument("--output", required=True)
    capture.set_defaults(handler=command_provenance_capture)
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--workspace", default=".")
    doctor.set_defaults(handler=command_doctor)
    xray = commands.add_parser("xray", help="inspect a local static path or already-captured artifact without execution")
    xray.add_argument("path", nargs="?")
    xray.add_argument("--database")
    xray.add_argument("--artifacts")
    xray.add_argument("--project")
    xray.add_argument("--source-artifact-digest")
    xray.add_argument("--source-kind", choices=["auto", "repository", "acp", "cli", "sdk", "otel_bundle", "recorded_run"], default="auto")
    xray.add_argument("--profile-id")
    xray.set_defaults(handler=command_xray)
    replay = commands.add_parser("counterfactual-replay", help="evaluate a recorded checkpointed paired replay without starting a provider")
    replay.add_argument("--input", required=True)
    replay.add_argument("--output")
    replay.add_argument("--live", action="store_true")
    replay.add_argument("--credentials-configured", action="store_true")
    replay.add_argument("--budget-usd", type=float)
    replay.add_argument("--live-policy-digest")
    replay.set_defaults(handler=command_counterfactual_replay)
    replay_alias = commands.add_parser("replay", help="alias for counterfactual-replay")
    replay_alias.add_argument("--input", required=True)
    replay_alias.add_argument("--output")
    replay_alias.add_argument("--live", action="store_true")
    replay_alias.add_argument("--credentials-configured", action="store_true")
    replay_alias.add_argument("--budget-usd", type=float)
    replay_alias.add_argument("--live-policy-digest")
    replay_alias.set_defaults(handler=command_counterfactual_replay)
    harness_ci = commands.add_parser("harness-ci", help="run provider-free base-versus-candidate Harness CI")
    harness_ci.add_argument("--replay", required=True)
    harness_ci.add_argument("--base", required=True)
    harness_ci.add_argument("--candidate", required=True)
    harness_ci.add_argument("--policy", required=True)
    harness_ci.add_argument("--output")
    harness_ci.add_argument("--summary")
    harness_ci.add_argument("--comment-output")
    harness_ci.set_defaults(handler=command_harness_ci)
    forge = commands.add_parser("forge", help="inspect untrusted Arena Forge controls without starting providers")
    forge_commands = forge.add_subparsers(dest="forge_command", required=True)
    forge_proposal = forge_commands.add_parser("proposal", help="validate an untrusted digest-bound proposal and retain a HOLD handoff")
    forge_proposal.add_argument("--input", required=True)
    forge_proposal.add_argument("--output")
    forge_proposal.set_defaults(handler=command_forge_proposal)
    forge_plan = forge_commands.add_parser("plan", help="rank budget- and risk-constrained experiment designs without execution")
    forge_plan.add_argument("--input", required=True)
    forge_plan.add_argument("--output")
    forge_plan.set_defaults(handler=command_forge_plan)
    forge_safety = forge_commands.add_parser("process-safety", help="evaluate digest-only information-flow controls without execution")
    forge_safety.add_argument("--input", required=True)
    forge_safety.add_argument("--output")
    forge_safety.set_defaults(handler=command_forge_process_safety)
    forge_evaluate = forge_commands.add_parser("evaluate", help="emit the custody prerequisites for a durable independent evaluation")
    forge_evaluate.set_defaults(handler=command_forge_evaluate_hold)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)
    serve.add_argument("--enable-offline-demo", action="store_true", help="enable the bundled synthetic fixture only on this literal loopback personal server")
    serve.set_defaults(handler=command_serve)
    worker = commands.add_parser("worker")
    mode = worker.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--healthcheck", action="store_true")
    worker.set_defaults(handler=command_worker)
    pack = commands.add_parser("pack")
    pack_sub = pack.add_subparsers(dest="pack_command", required=True)
    validate = pack_sub.add_parser("validate")
    validate.add_argument("pack")
    validate.set_defaults(handler=command_pack_validate)
    adapter = commands.add_parser("adapter")
    adapter_sub = adapter.add_subparsers(dest="adapter_command", required=True)
    certify = adapter_sub.add_parser("certify")
    certify.add_argument("--config", required=True)
    certify.set_defaults(handler=command_adapter_certify)
    experiment = commands.add_parser("experiment")
    experiment_sub = experiment.add_subparsers(dest="experiment_command", required=True)
    plan = experiment_sub.add_parser("plan")
    plan.add_argument("--spec", required=True)
    plan.set_defaults(handler=command_experiment_plan)
    preflight = experiment_sub.add_parser("preflight")
    _add_database_arguments(preflight)
    preflight.add_argument("experiment_id")
    preflight.set_defaults(handler=command_experiment_preflight)
    run = experiment_sub.add_parser("run")
    _add_database_arguments(run, execution=True)
    run.add_argument("experiment_id")
    run.add_argument("--provenance", required=True)
    run.set_defaults(handler=command_experiment_run)
    resume = experiment_sub.add_parser("resume")
    _add_database_arguments(resume)
    resume.add_argument("execution_id")
    resume.set_defaults(handler=command_experiment_resume)
    results = commands.add_parser("results")
    results_sub = results.add_subparsers(dest="results_command", required=True)
    analyze = results_sub.add_parser("analyze")
    _add_database_arguments(analyze)
    analyze.add_argument("--input", required=True)
    analyze.set_defaults(handler=command_results_analyze)
    results_export = results_sub.add_parser("export")
    _add_database_arguments(results_export)
    results_export.add_argument("report_digest")
    results_export.add_argument("--format", choices=["csv", "parquet"], default="csv")
    results_export.add_argument("--output", required=True)
    results_export.set_defaults(handler=command_results_export)
    brief = results_sub.add_parser("brief")
    _add_database_arguments(brief)
    brief.add_argument("--input", required=True)
    brief.set_defaults(handler=command_results_brief)
    evidence = commands.add_parser("evidence")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    verify = evidence_sub.add_parser("verify")
    verify.add_argument("--receipt", required=True)
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--artifacts", required=True)
    verify.add_argument(
        "--evidence-type",
        required=True,
        choices=[
            "fixture",
            "local_live",
            "reproduction",
            "cross_model",
            "human_calibration",
            "independent_reproduction",
        ],
    )
    verify.add_argument("--verifier-id", required=True)
    verify.add_argument("--verifier-digest", required=True)
    verify.set_defaults(handler=command_evidence_verify)
    export = commands.add_parser("export")
    _add_database_arguments(export)
    export.add_argument("study_pack_id")
    export.add_argument("version")
    export.add_argument("--output", required=True)
    export.set_defaults(handler=command_export)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.handler
    return handler(args)
