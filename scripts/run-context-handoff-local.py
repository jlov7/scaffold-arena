#!/usr/bin/env python3
"""Run the one frozen local study; default is provider-free preflight only."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from adapters_v1 import AdapterRegistry
from adapters_v1.context_handoff import ContextHandoffOllamaAdapter
from arena_cli.provenance import (
    _check_capture_budget,
    _eligible_relative,
    collect_study_pack_provenance,
)
from artifacts_v1 import LocalArtifactStore
from evaluation_v1 import EvaluationWorker, TrustedGraderRegistry
from execution_v1 import CentralPriceResolver, DurableWorker
from persistence_v1 import ArenaRepository, create_persistence_engine
from persistence_v1.schema import executions, metadata
from protocol_v1 import canonical_json, load_study_pack
from protocol_v1.canonical import sha256, sha256_bytes
from services_v1.execution import ExecutionService
from services_v1.registry import ProtocolRegistryService
from sqlalchemy import select

STUDY_PACK = ROOT / "study_packs/context-handoff-local-v1"
PROJECT_ID = "context-handoff-local"
SCHEDULE = "org.scaffold-arena.context-handoff-schedule-v1"


class ContextStudyError(RuntimeError):
    pass


def _json_bytes(value: Any) -> bytes:
    return canonical_json(
        json.loads(
            json.dumps(
                value,
                default=lambda item: (
                    item.isoformat() if hasattr(item, "isoformat") else str(item)
                ),
            )
        )
    )


def _write(path: Path, value: Any) -> None:
    """Atomic, fsynced checkpoint; previous checkpoint survives interruption."""
    descriptor, name = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(_json_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(name, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _clean_revision(repo_root: Path) -> str:
    status = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status.strip():
        raise ContextStudyError(
            "clean committed candidate required before execution creation"
        )
    return subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


async def _registry(adapter: ContextHandoffOllamaAdapter) -> AdapterRegistry:
    registry = AdapterRegistry()
    capabilities = await adapter.describe_capabilities()
    await registry.install_trusted(adapter, capabilities.adapter_digest)
    return registry


def _snapshot(repository: ArenaRepository, execution_id: str) -> dict[str, Any]:
    binding, rows, prices = repository.derived_execution_evidence_source(
        PROJECT_ID, execution_id
    )
    with repository.engine.connect() as conn:
        execution = dict(
            conn.execute(select(executions).where(executions.c.id == execution_id))
            .mappings()
            .one()
        )
    return {"binding": binding, "rows": rows, "prices": prices, "execution": execution}


def _ledger(
    pack: Any, snapshot: dict[str, Any], fatal_reason: str | None
) -> dict[str, Any]:
    rows = {
        row["episode_metadata"]["frozen_schedule_ordinal"]: row
        for row in snapshot["rows"]
    }
    cells = []
    for cell in pack.experiments[0].extensions[SCHEDULE]["cells"]:
        row = rows[cell["ordinal"]]
        status = row["attempt_status"]
        if status == "queued":
            status = "not_started_due_to_fatal_stop" if fatal_reason else "planned"
        cells.append(
            {
                "cell": cell,
                "attempt_id": row["attempt_id"],
                "status": status,
                "reason": fatal_reason
                if status == "not_started_due_to_fatal_stop"
                else None,
            }
        )
    complete = fatal_reason is None and all(
        row["attempt_status"] == "completed" and len(row["evaluations"]) == 1
        for row in rows.values()
    )
    return {
        "format": "context-handoff-local-ledger-v2",
        "execution_id": snapshot["execution"]["id"],
        "freeze_hash": snapshot["binding"]["spec_hash"],
        "fatal_reason": fatal_reason,
        "study_status": "completed" if complete else "partial",
        "attempts": cells,
        "evidence": snapshot,
    }


def _seal(output: Path) -> None:
    files = {
        path.relative_to(output).as_posix(): sha256_bytes(path.read_bytes())
        for path in sorted(output.rglob("*"))
        if path.is_file() and path != output / "manifest.json"
    }
    _write(
        output / "manifest.json",
        {
            "format": "context-handoff-evidence-manifest-v1",
            "files": files,
            "bundle_hash": sha256(files),
            "integrity_not_truth": True,
        },
    )


def _flush_retained_inputs(output: Path) -> None:
    """Flush copied pack/source bytes before the first runtime observation."""
    for path in output.rglob("*"):
        if path.is_file():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
    for path in [output, *(p for p in output.rglob("*") if p.is_dir())]:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


async def run_context_handoff_study(
    *, output: Path, adapter: ContextHandoffOllamaAdapter, repo_root: Path = ROOT
) -> dict[str, Any]:
    if output.exists():
        raise ContextStudyError("output root must be absent")
    if output.resolve().is_relative_to(repo_root.resolve()):
        raise ContextStudyError(
            "evidence output must be outside the clean candidate checkout"
        )
    _clean_revision(repo_root)
    pack = load_study_pack(STUDY_PACK)
    material: dict[str, Any] = {}
    capture = collect_study_pack_provenance(
        repository_root=repo_root,
        study_pack_path=STUDY_PACK / "study-pack.json",
        capture_material=material,
    )
    if capture.repository_dirty:
        raise ContextStudyError("provenance capture found a dirty candidate")
    output.mkdir(parents=True)
    shutil.copytree(STUDY_PACK, output / "study-pack")
    # Retain the eligible committed source bytes behind the observed Git index.
    # Secret-like paths and symlinks remain excluded by the capture contract.
    count, total = 0, 0
    for entry in base64.b64decode(
        material["git_observations"]["tracked_index_hash"]
    ).split(b"\0"):
        if not entry:
            continue
        header, relative_bytes = entry.split(b"\t", 1)
        mode, blob, stage = header.decode().split()
        relative = Path(relative_bytes.decode())
        if not _eligible_relative(relative) or mode not in {"100644", "100755"}:
            continue
        source = repo_root / relative
        if source.is_symlink() or not source.resolve().is_relative_to(
            repo_root.resolve()
        ):
            raise ContextStudyError("source path is not a regular in-tree file")
        content = source.read_bytes()
        count, total = count + 1, total + len(content)
        _check_capture_budget(
            file_count=count,
            total_bytes=total,
            file_bytes=len(content),
            file_message="source file exceeds capture limit",
        )
        if (
            stage != "0"
            or hashlib.sha1(
                b"blob " + str(len(content)).encode() + b"\0" + content
            ).hexdigest()
            != blob
        ):
            raise ContextStudyError("source changed after clean capture")
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    _write(
        output / "provenance.json",
        {"capture": capture.model_dump(mode="json"), "material": material},
    )
    _write(
        output / "planned.json",
        {
            "study_pack_hash": sha256(pack.model_dump(mode="json")),
            "schedule": pack.experiments[0].extensions[SCHEDULE],
        },
    )
    engine = create_persistence_engine(f"sqlite:///{output / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Local context-handoff study", project_id=PROJECT_ID)
    store = LocalArtifactStore(output / "artifacts")
    execution = None
    report = None
    fatal_reason = None
    transport: list[dict[str, Any]] = []
    accounting: list[dict[str, Any]] = []
    ledger = None

    def retain(
        attempt_id: str, method: str, url: str, phase: str, content: bytes
    ) -> None:
        digest = store.put_bytes(content)
        repository.register_artifact(
            digest,
            size_bytes=len(content),
            storage_uri=store.uri_for(digest),
            media_type="application/octet-stream",
            content_metadata={"artifact_role": "local_transport"},
        )
        transport.append(
            {
                "attempt_id": attempt_id,
                "sequence": len(transport),
                "method": method,
                "url": url,
                "phase": phase,
                "digest": digest,
            }
        )
        _write(output / "transport.json", transport)
        if method == "POST" and phase == "request":
            request = json.loads(content)
            prompt = request["messages"][0]["content"].encode()
            prompt_hash = sha256_bytes(prompt)
            accounting.append(
                {
                    "attempt_id": attempt_id,
                    "request_digest": digest,
                    "prompt_hash": prompt_hash,
                    "prompt_bytes": len(prompt),
                    "exact_prefix_hash": prompt_hash,
                    "previous_request_digest": accounting[-1]["request_digest"]
                    if accounting
                    else None,
                    "equal_to_previous_prompt": prompt_hash
                    == accounting[-1]["prompt_hash"]
                    if accounting
                    else None,
                    "cache_observation": "unavailable",
                    "cached_input_tokens": None,
                    "cache_savings_tokens": None,
                    "cache_savings_usd": None,
                    "energy": "unknown",
                }
            )
            _write(output / "accounting.json", accounting)

    adapter.evidence_sink = retain
    _write(output / "transport.json", transport)
    _write(output / "accounting.json", accounting)
    try:
        registry = await _registry(adapter)
        protocol = ProtocolRegistryService(
            repository, store, adapter_registry=registry, personal_project_id=PROJECT_ID
        )
        imported = protocol.import_pack(
            canonical_json(pack.model_dump(mode="json")),
            "application/json",
            project_id=PROJECT_ID,
        )
        created = protocol.create_experiment(
            pack.experiments[0].model_dump(mode="json"), project_id=PROJECT_ID
        )
        frozen = protocol.freeze(created["experiment_id"], project_id=PROJECT_ID)
        report = protocol.preflight(created["experiment_id"], project_id=PROJECT_ID)
        _write(output / "preflight.json", report)
        _write(output / "registry.json", {"imported": imported, "frozen": frozen})
        if report["verdict"] != "PASS":
            raise ContextStudyError("registry_preflight_hold")
        if _clean_revision(repo_root) != capture.provenance.code_revision:
            raise ContextStudyError("candidate changed after provenance capture")
        service = ExecutionService(
            repository, store, adapter_registry=registry, personal_project_id=PROJECT_ID
        )
        execution = service.create_execution(
            created["experiment_id"],
            capture.provenance.model_dump(mode="json"),
            project_id=PROJECT_ID,
            request_key="context-handoff-local-v1",
        )
        initial = _snapshot(repository, execution["execution_id"])
        if len(initial["rows"]) != 24 or any(
            row["attempt_status"] != "queued" for row in initial["rows"]
        ):
            raise ContextStudyError("planned_matrix_not_materialized")
        _write(output / "initial.json", initial)
        _write(output / "ledger.json", _ledger(pack, initial, None))
        _flush_retained_inputs(output)
        deadline = datetime.fromisoformat(
            initial["execution"]["parameters"]["aggregate_deadline_at"]
        )
        worker = DurableWorker(
            repository,
            registry,
            store,
            price_resolver=CentralPriceResolver(),
            project_id=PROJECT_ID,
            terminalize_on_cancel=True,
        )
        evaluator = EvaluationWorker(
            repository, store, TrustedGraderRegistry(), project_id=PROJECT_ID
        )
        for _ in range(24):
            remaining = (deadline - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                fatal_reason = "aggregate_wall_time_stop"
                break
            result = await asyncio.wait_for(
                worker.run_once(
                    "context-handoff-worker",
                    lease_seconds=min(180.0, remaining),
                    execution_id=execution["execution_id"],
                ),
                timeout=remaining,
            )
            if result is None:
                fatal_reason = "unexpected_unavailable_job"
                break
            if result.status != "completed":
                fatal_reason = result.detail or result.status
            captured = _snapshot(repository, execution["execution_id"])
            current = next(
                row
                for row in captured["rows"]
                if any(job["id"] == result.job_id for job in row["jobs"])
            )
            if current["attempt_status"] != "completed":
                fatal_reason = fatal_reason or current["attempt_status"]
                terminal_receipt = (
                    (current.get("result_metadata") or {})
                    .get("artifact_ids", {})
                    .get("context-terminal-receipt")
                )
                if terminal_receipt:
                    fatal_reason = (
                        json.loads(store.get_bytes(terminal_receipt)).get("detail")
                        or fatal_reason
                    )
            evaluated = evaluator.run_once(
                "context-handoff-evaluator",
                lease_seconds=60.0,
                execution_id=execution["execution_id"],
            )
            if evaluated is not None and evaluated.status != "completed":
                fatal_reason = fatal_reason or evaluated.detail or evaluated.status
            _write(
                output / "ledger.json",
                _ledger(
                    pack, _snapshot(repository, execution["execution_id"]), fatal_reason
                ),
            )
            if fatal_reason:
                break
    except BaseException as exc:
        fatal_reason = (
            "aggregate_wall_time_stop"
            if isinstance(exc, TimeoutError)
            else type(exc).__name__
        )
        _write(
            output / "stop.json",
            {"reason": fatal_reason, "exception_type": type(exc).__name__},
        )
        if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
            raise
    finally:
        if execution is not None:
            ledger = _ledger(
                pack, _snapshot(repository, execution["execution_id"]), fatal_reason
            )
            _write(output / "ledger.json", ledger)
        else:
            _write(
                output / "stop.json",
                {
                    "reason": fatal_reason,
                    "study_status": "not_created",
                    "planned_cells": 24,
                },
            )
        adapter.evidence_sink = None
        await adapter._client.aclose()
        engine.dispose()
        _seal(output)
    return {"preflight": report, "ledger": ledger, "fatal_reason": fatal_reason}


async def preflight() -> dict[str, Any]:
    pack = load_study_pack(STUDY_PACK)
    with tempfile.TemporaryDirectory(prefix="scaffold-context-preflight-") as temporary:
        engine = create_persistence_engine(f"sqlite:///{Path(temporary) / 'arena.db'}")
        metadata.create_all(engine)
        repository = ArenaRepository(engine)
        repository.create_project(
            "Local context-handoff preflight", project_id=PROJECT_ID
        )
        adapter = ContextHandoffOllamaAdapter(endpoint="http://127.0.0.1:11434/api")
        try:
            registry = await _registry(adapter)
            protocol = ProtocolRegistryService(
                repository,
                LocalArtifactStore(Path(temporary) / "artifacts"),
                adapter_registry=registry,
                personal_project_id=PROJECT_ID,
            )
            protocol.import_pack(
                canonical_json(pack.model_dump(mode="json")),
                "application/json",
                project_id=PROJECT_ID,
            )
            created = protocol.create_experiment(
                pack.experiments[0].model_dump(mode="json"), project_id=PROJECT_ID
            )
            protocol.freeze(created["experiment_id"], project_id=PROJECT_ID)
            return protocol.preflight(created["experiment_id"], project_id=PROJECT_ID)
        finally:
            await adapter._client.aclose()
            engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--dispatch", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.dispatch:
        if args.output is None:
            parser.error("--dispatch requires --output")
        result = asyncio.run(
            run_context_handoff_study(
                output=args.output,
                adapter=ContextHandoffOllamaAdapter(
                    endpoint="http://127.0.0.1:11434/api"
                ),
            )
        )
        print(
            json.dumps(
                {
                    "fatal_reason": result["fatal_reason"],
                    "study_status": result["ledger"]["study_status"]
                    if result["ledger"]
                    else "not_created",
                }
            )
        )
        return (
            0
            if result["ledger"] and result["ledger"]["study_status"] == "completed"
            else 1
        )
    if args.output:
        parser.error("--output requires --dispatch")
    report = asyncio.run(preflight())
    print(json.dumps(report, sort_keys=True, default=str))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
