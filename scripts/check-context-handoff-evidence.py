#!/usr/bin/env python3
"""Offline custody verification and evaluator replay; never invokes a provider.

Hashes establish internal consistency, not a signed attestation of inference.
An intact fatal partial study is explicitly different from a completed study.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from adapters_v1 import AttemptExecutionControls, AttemptInput
from adapters_v1.context_handoff.models import (
    CONTEXT_HANDOFF_NAMESPACE,
    EXPECTED_MODEL_DIGEST,
    EXPECTED_OLLAMA_VERSION,
    ContextPacket,
)
from adapters_v1.context_handoff.render import render_context
from adapters_v1.controls import AppliedControls, scenario_with_execution_controls
from adapters_v1.models import ProviderUsage
from arena_cli.provenance import _eligible_relative, _source_refs
from artifacts_v1 import LocalArtifactStore
from evaluation_v1 import TrustedGraderRegistry
from execution_v1 import CentralPriceResolver, ExperimentController
from persistence_v1 import ArenaRepository, create_persistence_engine
from persistence_v1.schema import artifacts, evaluations, executions
from protocol_v1 import ExperimentSpec, canonical_json, load_study_pack
from protocol_v1.canonical import sha256, sha256_bytes
from protocol_v1.study_pack import freeze_experiment
from services_v1.evaluation import DurableEvaluationService
from sqlalchemy import delete, select

PROJECT_ID = "context-handoff-local"
SCHEDULE = "org.scaffold-arena.context-handoff-schedule-v1"


def _normal(value: Any) -> Any:
    return json.loads(
        json.dumps(
            value,
            default=lambda item: (
                item.isoformat() if hasattr(item, "isoformat") else str(item)
            ),
        )
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


class _ReadOnlyArtifacts(LocalArtifactStore):
    def __init__(self, root: Path):
        super().__init__(root)
        self.registered_uris: dict[str, str] = {}

    def uri_for(self, digest: str) -> str:
        # Preserve the original custody label when the evaluator re-registers
        # a known artifact. Reads always use the recipient's content store;
        # original absolute paths are never opened.
        return self.registered_uris[digest]

    def put_bytes(self, content: bytes, **_: Any) -> str:
        digest = sha256_bytes(content)
        _require(
            self.get_bytes(digest) == content,
            "replayed evaluator result differs from retained bytes",
        )
        return digest


def _verify(root: Path) -> dict[str, Any]:
    _require(
        root.is_dir() and not root.is_symlink(),
        "evidence root must be a regular directory",
    )
    manifest = json.loads((root / "manifest.json").read_bytes())
    inventory = {}
    for path in sorted(root.rglob("*")):
        _require(not path.is_symlink(), "symlink evidence is forbidden")
        if path.is_file() and path != root / "manifest.json":
            inventory[path.relative_to(root).as_posix()] = sha256_bytes(
                path.read_bytes()
            )
    _require(
        manifest.get("format") == "context-handoff-evidence-manifest-v1"
        and manifest.get("files") == inventory
        and manifest.get("bundle_hash") == sha256(inventory),
        "evidence file census or digest mismatch",
    )
    pack = load_study_pack(root / "study-pack")
    # This command accepts only the shipped frozen study, not caller-authored
    # replacement tasks, cohorts, runtime identities, graders or budgets.
    trusted = load_study_pack(ROOT / "study_packs/context-handoff-local-v1")
    _require(pack == trusted, "retained study differs from the frozen supported study")
    trusted_root = ROOT / "study_packs/context-handoff-local-v1"
    _require(
        {
            p.relative_to(root / "study-pack").as_posix(): p.read_bytes()
            for p in (root / "study-pack").rglob("*")
            if p.is_file()
        }
        == {
            p.relative_to(trusted_root).as_posix(): p.read_bytes()
            for p in trusted_root.rglob("*")
            if p.is_file()
        },
        "retained source fixtures differ from frozen pack",
    )
    schedule = _normal(pack.experiments[0].extensions[SCHEDULE])
    planned = json.loads((root / "planned.json").read_bytes())
    _require(
        planned
        == {
            "study_pack_hash": sha256(pack.model_dump(mode="json")),
            "schedule": schedule,
        },
        "planned schedule binding mismatch",
    )
    provenance = json.loads((root / "provenance.json").read_bytes())
    capture, material = provenance["capture"], provenance["material"]
    observed = capture["provenance"]
    _require(
        capture["repository_dirty"] is False
        and capture["capture_method"] == "automatic-local-v1",
        "candidate provenance is not clean automatic capture",
    )
    for field in (
        "code_hash",
        "runtime_image_hash",
        "environment_hash",
        "prompt_hash",
        "context_hash",
        "tool_hash",
    ):
        _require(
            sha256(material[field]) == observed[field],
            f"provenance {field} lacks matching observed material",
        )
    _require(
        material["code_hash"]["revision"] == observed["code_revision"],
        "code revision mismatch",
    )
    for field, encoded in material["git_observations"].items():
        _require(
            sha256_bytes(base64.b64decode(encoded, validate=True))
            == material["code_hash"][field],
            "Git observation digest mismatch",
        )
    expected_sources = set()
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
        content = (root / "source" / relative).read_bytes()
        expected_sources.add(relative.as_posix())
        _require(
            stage == "0"
            and hashlib.sha1(
                b"blob " + str(len(content)).encode() + b"\0" + content
            ).hexdigest()
            == blob,
            "retained source differs from clean Git index",
        )
    _require(
        {
            p.relative_to(root / "source").as_posix()
            for p in (root / "source").rglob("*")
            if p.is_file()
        }
        == expected_sources,
        "retained source census mismatch",
    )
    _require(
        material["runtime_image_hash"]["label"] == observed["runtime_image"],
        "Python runtime label mismatch",
    )
    for lock in material["environment_hash"]["lockfiles"]:
        relative = Path(lock["path"])
        _require(
            _eligible_relative(relative)
            and sha256_bytes((root / "source" / relative).read_bytes())
            == lock["sha256"],
            "dependency lockfile provenance mismatch",
        )
    expected_refs = [
        ref.model_dump(mode="json")
        for ref in _source_refs(pack, root / "study-pack/study-pack.json")
    ]
    _require(
        observed["source_refs"] == expected_refs,
        "source bytes or provenance references mismatch",
    )
    prompts = [
        {
            "scenario_id": s.scenario_id,
            "prompt": s.prompt,
            "output_contract": s.output_contract.model_dump(mode="json")
            if s.output_contract
            else None,
        }
        for s in sorted(pack.scenarios, key=lambda s: s.scenario_id)
    ]
    _require(
        material["prompt_hash"] == prompts,
        "prompt provenance differs from frozen tasks",
    )
    context_fields = {
        "scenario_id": "scenario_id",
        "extensions": "extensions",
        "source_label": "source_label",
        "data_classification": "data_classification",
        "control_role": "control_role",
        "cluster_id": "cluster_id",
        "variant": "variant",
        "pair_id": "pair_id",
        "initial_state": "initial_state",
        "reference_solution": "reference_solution",
        "evidence_sources": "evidence_sources",
        "faults": "fault_definitions",
        "fault_schedule": "fault_schedule",
        "allowed_claims": "allowed_claims",
        "limitations": "limitations",
    }
    _require(
        material["context_hash"]
        == [
            {k: s.model_dump(mode="json")[field] for k, field in context_fields.items()}
            for s in sorted(pack.scenarios, key=lambda s: s.scenario_id)
        ],
        "context provenance differs from frozen packets",
    )
    tools = {
        "scenario_tools": [
            {
                "scenario_id": s.scenario_id,
                "fixtures": [f.model_dump(mode="json") for f in s.tool_fixtures],
            }
            for s in sorted(pack.scenarios, key=lambda s: s.scenario_id)
        ],
        "harness_tools": [
            {
                "harness_id": h.harness_id,
                "allowed_tools": list(h.allowed_tools),
                "capabilities": h.capabilities.model_dump(mode="json"),
                "schema_hashes": h.schema_hashes.model_dump(mode="json"),
            }
            for h in sorted(pack.harnesses, key=lambda h: h.harness_id)
        ],
    }
    _require(material["tool_hash"] == tools, "tool provenance mismatch")
    if not (root / "ledger.json").exists():
        stop = json.loads((root / "stop.json").read_bytes())
        _require(
            stop.get("study_status") == "not_created"
            and stop.get("planned_cells") == 24,
            "pre-execution stop lacks fixed denominator",
        )
        _require(
            json.loads((root / "transport.json").read_bytes()) == [],
            "provider activity before execution creation",
        )
        return {
            "integrity": "PASS",
            "study_status": "not_created",
            "completed": False,
            "errors": [],
        }
    ledger = json.loads((root / "ledger.json").read_bytes())
    initial = json.loads((root / "initial.json").read_bytes())
    transport = json.loads((root / "transport.json").read_bytes())
    retained_accounting = json.loads((root / "accounting.json").read_bytes())
    _require(
        [t["sequence"] for t in transport] == list(range(len(transport))),
        "transport order discontinuity",
    )
    _require(
        ledger.get("format") == "context-handoff-local-ledger-v2",
        "invalid ledger format",
    )
    with tempfile.TemporaryDirectory(prefix="context-evidence-replay-") as temporary:
        # Replay mutates only a private DB copy. The recipient's sealed root is
        # never migrated, updated, resumed or used to execute jobs.
        replay = Path(temporary) / "arena.db"
        shutil.copyfile(root / "arena.db", replay)
        engine = create_persistence_engine(f"sqlite:///{replay}")
        repository = ArenaRepository(engine)
        store = _ReadOnlyArtifacts(root / "artifacts")
        try:
            binding, rows, prices = repository.derived_execution_evidence_source(
                PROJECT_ID, ledger["execution_id"]
            )
            with engine.connect() as conn:
                execution = dict(
                    conn.execute(
                        select(executions).where(
                            executions.c.id == ledger["execution_id"]
                        )
                    )
                    .mappings()
                    .one()
                )
                registered = conn.execute(select(artifacts)).mappings().all()
            snapshot = _normal(
                {
                    "binding": binding,
                    "rows": rows,
                    "prices": prices,
                    "execution": execution,
                }
            )
            _require(
                ledger["evidence"] == snapshot,
                "ledger differs from durable database evidence",
            )
            for artifact in registered:
                store.registered_uris[artifact["digest"]] = artifact["storage_uri"]
                _require(
                    len(store.get_bytes(artifact["digest"])) == artifact["size_bytes"],
                    "artifact registry byte count mismatch",
                )
            _require(binding is not None, "execution is absent")
            spec = ExperimentSpec.model_validate_json(
                canonical_json(binding["definition"])
            )
            unfrozen = ExperimentSpec.model_validate_json(
                canonical_json(
                    spec.model_dump(mode="json")
                    | {"frozen": False, "frozen_at": None, "freeze_hash": None}
                )
            )
            _require(
                freeze_experiment(unfrozen, spec.study_pack_hash).freeze_hash
                == spec.freeze_hash
                == ledger["freeze_hash"]
                == binding["spec_hash"],
                "freeze hash mismatch",
            )
            expected_spec = pack.experiments[0].model_dump(
                mode="json",
                exclude={"frozen", "frozen_at", "freeze_hash", "study_pack_hash"},
            )
            _require(
                spec.model_dump(
                    mode="json",
                    exclude={"frozen", "frozen_at", "freeze_hash", "study_pack_hash"},
                )
                == expected_spec,
                "frozen experiment differs from declared design",
            )
            params = execution["parameters"]
            report = json.loads((root / "preflight.json").read_bytes())
            _require(
                report["verdict"] == "PASS" and report["expected_attempts"] == 24,
                "preflight does not admit the frozen24",
            )
            _require(
                params == initial["execution"]["parameters"]
                and params["provenance"] == observed,
                "execution controls/provenance changed after creation",
            )
            _require(
                (
                    datetime.fromisoformat(params["aggregate_deadline_at"])
                    - datetime.fromisoformat(params["aggregate_started_at"])
                ).total_seconds()
                == spec.aggregate_budget.max_wall_time_seconds
                == 4320,
                "aggregate deadline is not bound to durable creation",
            )
            scenarios = {s.scenario_id: s for s in pack.scenarios}
            harness = pack.harnesses[0]
            units = ExperimentController(repository)._matrix(spec, scenarios)
            _require(
                len(rows)
                == len(initial["rows"])
                == len(units)
                == len(ledger["attempts"])
                == 24,
                "fixed denominator/replacement mismatch",
            )
            by_ordinal = {
                r["episode_metadata"]["frozen_schedule_ordinal"]: r for r in rows
            }
            before = {
                r["episode_metadata"]["frozen_schedule_ordinal"]: r
                for r in initial["rows"]
            }
            _require(
                set(by_ordinal) == set(before) == set(range(24)),
                "missing or duplicate planned coordinate",
            )
            started_ids = set()
            completed = True
            accounting = []
            evaluator = DurableEvaluationService(
                repository, store, TrustedGraderRegistry()
            )
            for ordinal, unit in enumerate(units):
                row, original = by_ordinal[ordinal], before[ordinal]
                cell = schedule["cells"][ordinal]
                _require(
                    _normal(row["episode_metadata"])
                    == _normal(unit | {"scenario_id": unit["scenario_id"]})
                    or _normal(row["episode_metadata"])
                    == _normal({k: v for k, v in unit.items() if k != "scenario_id"}),
                    f"schedule/seed mismatch at {ordinal}",
                )
                _require(
                    row["attempt_id"] == original["attempt_id"]
                    and original["attempt_status"] == "queued"
                    and row["attempt_ordinal"] == 0,
                    f"replacement at {ordinal}",
                )
                attempt_jobs = [j for j in row["jobs"] if j["kind"] == "attempt"]
                _require(
                    len(attempt_jobs) == 1 and attempt_jobs[0]["attempt_count"] <= 1,
                    f"retry at {ordinal}",
                )
                job = attempt_jobs[0]
                old_job = next(j for j in original["jobs"] if j["kind"] == "attempt")
                _require(
                    _normal(job["payload"]) == old_job["payload"],
                    f"durable job changed at {ordinal}",
                )
                queued = AttemptInput.model_validate_json(
                    canonical_json(job["payload"]["attempt_input"])
                )
                controls = AttemptExecutionControls.from_experiment(
                    spec, seed=unit["seed"], harness=harness
                )
                expected_envelope = ExperimentController._envelope(
                    spec,
                    unit,
                    queued.attempt.episode_id,
                    queued.attempt.attempt_id,
                    queued.attempt.provenance,
                )
                expected_envelope["queued_at"] = queued.attempt.model_dump(mode="json")[
                    "queued_at"
                ]
                expected_envelope["request_hash"] = sha256(
                    {
                        "base_request_hash": expected_envelope["request_hash"],
                        "execution_controls_digest": controls.digest,
                    }
                )
                _require(
                    queued.attempt.model_dump(mode="json") == expected_envelope
                    and row["request_metadata"]["envelope"] == expected_envelope,
                    f"canonical envelope/request hash mismatch at {ordinal}",
                )
                _require(
                    job["payload"]["aggregate_budget"]
                    == spec.aggregate_budget.model_dump(mode="json")
                    | {"deadline_at": params["aggregate_deadline_at"]},
                    f"job aggregate deadline changed at {ordinal}",
                )
                _require(
                    queued.execution_controls == controls
                    and queued.scenario
                    == scenario_with_execution_controls(
                        scenarios[cell["scenario_id"]], controls
                    ),
                    f"frozen request/scenario controls mismatch at {ordinal}",
                )
                _require(
                    job["payload"]["harness"] == harness.model_dump(mode="json")
                    and queued.attempt.provenance.model_dump(mode="json") == observed,
                    f"harness/provenance mismatch at {ordinal}",
                )
                _require(
                    queued.attempt.factor_assignments
                    == {"context_policy": cell["context_policy"]}
                    and queued.attempt.provider == "ollama"
                    and queued.attempt.provider_model == cell["provider_model"]
                    and queued.attempt.budget == spec.budgets,
                    f"model/factor/budget mismatch at {ordinal}",
                )
                status = row["attempt_status"]
                retained = ledger["attempts"][ordinal]
                expected_status = (
                    "not_started_due_to_fatal_stop"
                    if status == "queued" and ledger["fatal_reason"]
                    else status
                )
                _require(
                    retained
                    == {
                        "cell": cell,
                        "attempt_id": row["attempt_id"],
                        "status": expected_status,
                        "reason": ledger["fatal_reason"]
                        if expected_status == "not_started_due_to_fatal_stop"
                        else None,
                    },
                    f"ledger terminal mismatch at {ordinal}",
                )
                observed_transport = [
                    t for t in transport if t["attempt_id"] == row["attempt_id"]
                ]
                if status == "queued":
                    _require(
                        not observed_transport
                        and not row["evaluations"]
                        and job["attempt_count"] == 0
                        and bool(ledger["fatal_reason"]),
                        f"undispatched cell has activity or no stop at {ordinal}",
                    )
                    completed = False
                    continue
                started_ids.add(row["attempt_id"])
                _require(
                    status
                    in {
                        "completed",
                        "failed",
                        "timed_out",
                        "incomplete",
                        "cancelled",
                        "started",
                    },
                    f"invalid persisted attempt state at {ordinal}",
                )
                completed &= status == "completed" and len(row["evaluations"]) == 1
                metadata = row["result_metadata"] or {}
                if metadata.get("captured_adapter_terminal"):
                    terminal_receipt = json.loads(
                        store.get_bytes(
                            metadata["artifact_ids"]["context-terminal-receipt"]
                        )
                    )
                    _require(
                        terminal_receipt["attempt_id"] == row["attempt_id"]
                        and terminal_receipt["terminal_outcome"] == status
                        and terminal_receipt["usage"] == metadata["usage"]
                        and terminal_receipt["response_hash"]
                        == metadata["response_hash"],
                        f"adapter terminal receipt mismatch at {ordinal}",
                    )
                input_digest = metadata.get("input_artifact_digest")
                if input_digest:
                    started = AttemptInput.model_validate_json(
                        store.get_bytes(input_digest)
                    )
                    _require(
                        started.scenario == queued.scenario
                        and started.execution_controls == controls
                        and started.attempt.request_hash == queued.attempt.request_hash,
                        f"captured input changed at {ordinal}",
                    )
                posts = [
                    t
                    for t in observed_transport
                    if t["method"] == "POST" and t["phase"] == "request"
                ]
                _require(len(posts) <= 1, f"extra inference request at {ordinal}")
                for t in observed_transport:
                    _require(
                        (t["method"], t["url"])
                        in {
                            ("GET", "http://127.0.0.1:11434/api/version"),
                            ("GET", "http://127.0.0.1:11434/api/tags"),
                            ("POST", "http://127.0.0.1:11434/api/chat"),
                        },
                        "unapproved provider endpoint",
                    )
                    store.get_bytes(t["digest"])
                if posts:
                    packet = ContextPacket.model_validate(
                        scenarios[cell["scenario_id"]].extensions[
                            CONTEXT_HANDOFF_NAMESPACE
                        ]["packet"]
                    )
                    prompt, receipt = render_context(
                        task=scenarios[cell["scenario_id"]].prompt,
                        packet=packet,
                        policy=cell["context_policy"],
                    )
                    request = {
                        "model": "qwen3.5:4b",
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "think": False,
                        "options": {
                            "temperature": controls.temperature,
                            "top_p": controls.top_p,
                            "num_predict": 256,
                            "seed": unit["seed"],
                            "num_ctx": 4096,
                        },
                    }
                    _require(
                        store.get_bytes(posts[0]["digest"]) == canonical_json(request),
                        f"actual request/rendered delivery mismatch at {ordinal}",
                    )
                    accounting.append(
                        {
                            "attempt_id": row["attempt_id"],
                            "request_digest": posts[0]["digest"],
                            "prompt_hash": receipt.prompt_hash,
                            "prompt_bytes": receipt.prompt_bytes,
                            "exact_prefix_hash": sha256_bytes(prompt.encode()),
                            "previous_request_digest": accounting[-1]["request_digest"]
                            if accounting
                            else None,
                            "equal_to_previous_prompt": receipt.prompt_hash
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
                if status == "completed":
                    _require(
                        len(posts) == 1,
                        f"completed cell lacks exactly one request at {ordinal}",
                    )
                    ids = metadata["artifact_ids"]
                    applied = AppliedControls.model_validate_json(
                        store.get_bytes(ids["applied-controls"])
                    )
                    _require(
                        {c.control_id: c.requested_value for c in applied.controls}
                        == controls.control_values()
                        and all(
                            c.observed_value == c.requested_value
                            and c.status in {"applied", "bound"}
                            for c in applied.controls
                        ),
                        f"applied controls mismatch at {ordinal}",
                    )
                    trace = json.loads(
                        store.get_bytes(metadata["trace_artifact_digest"])
                    )
                    _require(
                        all(t["payload_hash"] == sha256(t["payload"]) for t in trace),
                        f"trace payload hash mismatch at {ordinal}",
                    )
                    requests = [t for t in trace if t["event_type"] == "request"]
                    _require(
                        len(requests) == 1
                        and requests[0]["payload"]["request_digest"]
                        == posts[0]["digest"],
                        f"trace/transport request mismatch at {ordinal}",
                    )
                    _require(
                        json.loads(store.get_bytes(ids["context-renderer-receipt"]))
                        == receipt.model_dump(mode="json")
                        and store.get_bytes(ids["rendered-context-prompt"])
                        == prompt.encode(),
                        f"renderer receipt/prompt mismatch at {ordinal}",
                    )
                    identities = json.loads(store.get_bytes(ids["runtime-identity"]))
                    _require(
                        identities["before"] == identities["after"],
                        f"runtime changed at {ordinal}",
                    )
                    for identity in identities.values():
                        _require(
                            identity["model_digest"] == EXPECTED_MODEL_DIGEST
                            and identity["ollama_version"] == EXPECTED_OLLAMA_VERSION
                            and identity["runtime_identity_digest"]
                            == sha256(
                                {
                                    k: v
                                    for k, v in identity.items()
                                    if k != "runtime_identity_digest"
                                }
                            ),
                            f"frozen runtime mismatch at {ordinal}",
                        )
                    responses = [
                        t
                        for t in observed_transport
                        if t["method"] == "POST" and t["phase"] == "response"
                    ]
                    versions = [
                        json.loads(store.get_bytes(t["digest"]))
                        for t in observed_transport
                        if t["phase"] == "response" and t["url"].endswith("/version")
                    ]
                    tags = [
                        json.loads(store.get_bytes(t["digest"]))
                        for t in observed_transport
                        if t["phase"] == "response" and t["url"].endswith("/tags")
                    ]
                    _require(
                        len(responses) == 1 and len(versions) == len(tags) == 2,
                        f"missing per-cell transport identity observations at {ordinal}",
                    )
                    _require(
                        [
                            (t["method"], t["url"].rsplit("/", 1)[-1], t["phase"])
                            for t in observed_transport
                        ]
                        == [
                            (method, path, phase)
                            for method, path in [
                                ("GET", "version"),
                                ("GET", "tags"),
                                ("POST", "chat"),
                                ("GET", "version"),
                                ("GET", "tags"),
                            ]
                            for phase in ["request", "response"]
                        ],
                        f"pre/post identity order mismatch at {ordinal}",
                    )
                    _require(
                        all(v["version"] == EXPECTED_OLLAMA_VERSION for v in versions)
                        and all(
                            len(
                                [
                                    m
                                    for m in t["models"]
                                    if m["name"] == "qwen3.5:4b"
                                    and m["digest"] == EXPECTED_MODEL_DIGEST
                                ]
                            )
                            == 1
                            for t in tags
                        ),
                        f"raw runtime identity mismatch at {ordinal}",
                    )
                    raw = store.get_bytes(responses[0]["digest"])
                    payload = json.loads(raw)
                    summary = json.loads(
                        store.get_bytes(ids["provider-response-summary"])
                    )
                    _require(
                        summary["raw_response_sha256"] == sha256_bytes(raw)
                        and all(
                            payload.get(k) == v for k, v in summary["response"].items()
                        ),
                        f"provider summary binding mismatch at {ordinal}",
                    )
                    usage = ProviderUsage.model_validate_json(
                        store.get_bytes(ids["provider-usage"])
                    )
                    _require(
                        usage.model_dump(mode="json") == metadata["usage"]
                        and usage.input_tokens == payload["prompt_eval_count"]
                        and usage.output_tokens == payload["eval_count"]
                        and usage.total_tokens
                        == usage.input_tokens + usage.output_tokens
                        and usage.provider_usage_digest
                        == sha256(
                            {
                                "raw_response_sha256": sha256_bytes(raw),
                                "runtime_identity": identities["after"],
                            }
                        ),
                        f"provider usage binding mismatch at {ordinal}",
                    )
                    _require(
                        usage.cached_input_tokens is None
                        and usage.input_tokens <= 3840
                        and usage.output_tokens <= 256
                        and usage.tool_calls == 0,
                        f"budget/cache mismatch at {ordinal}",
                    )
                    _require(
                        store.get_bytes(ids["assistant-output"])
                        == payload["message"]["content"].encode()
                        and payload["done"] is True
                        and payload["model"] == "qwen3.5:4b",
                        f"output response binding mismatch at {ordinal}",
                    )
                    quote = CentralPriceResolver().resolve(
                        provider="ollama", model_id="qwen3.5:4b", usage=usage
                    )
                    _require(
                        quote is not None
                        and quote.cost_usd == metadata["cost_usd"] == 0
                        and metadata["cost_status"] == "reconciled",
                        f"central pricing mismatch at {ordinal}",
                    )
                    _require(
                        usage.actual_cost_usd is None and len(row["usage_rows"]) == 1,
                        f"adapter price or usage census mismatch at {ordinal}",
                    )
                    cost = row["usage_rows"][0]
                    expected_cost = {
                        "model_id": "qwen3.5:4b",
                        "provider_usage_digest": usage.provider_usage_digest,
                        "price_catalog_revision": quote.price_catalog_revision,
                        "cost_usd": 0.0,
                        "actual_cost_usd": 0.0,
                        "cost_status": "reconciled",
                        "reserved_max_tokens": 4096,
                        "reserved_max_tool_calls": 0,
                    }
                    expected_cost.update(
                        {
                            k: getattr(usage, k)
                            for k in [
                                "input_tokens",
                                "output_tokens",
                                "total_tokens",
                                "context_tokens",
                                "tool_calls",
                            ]
                        }
                    )
                    _require(
                        all(cost.get(k) == v for k, v in expected_cost.items()),
                        f"usage ledger/catalogue mismatch at {ordinal}",
                    )
                for evaluation in row["evaluations"]:
                    _require(
                        sha256(evaluation["result"])
                        == evaluation["result_hash"]
                        == evaluation["result_artifact_digest"],
                        f"evaluation byte binding mismatch at {ordinal}",
                    )
                    _require(
                        json.loads(
                            store.get_bytes(evaluation["result_artifact_digest"])
                        )
                        == evaluation["result"],
                        f"evaluation artifact mismatch at {ordinal}",
                    )
                    # Reconstruct in a disposable DB without accepting a saved
                    # grader result as an evaluator input.
                    with engine.begin() as conn:
                        conn.execute(
                            delete(evaluations).where(
                                evaluations.c.attempt_id == row["attempt_id"]
                            )
                        )
                    evaluator.evaluate(PROJECT_ID, row["attempt_id"])
                    with engine.connect() as conn:
                        replayed = dict(
                            conn.execute(
                                select(evaluations).where(
                                    evaluations.c.attempt_id == row["attempt_id"]
                                )
                            )
                            .mappings()
                            .one()
                        )
                    _require(
                        _normal(
                            {k: v for k, v in replayed.items() if k != "created_at"}
                        )
                        == _normal(
                            {k: v for k, v in evaluation.items() if k != "created_at"}
                        ),
                        f"trusted evaluator replay differs at {ordinal}",
                    )
                if status == "completed":
                    _require(
                        len(row["evaluations"]) == 1,
                        f"missing trusted evaluation at {ordinal}",
                    )
            _require(
                all(t["attempt_id"] in started_ids for t in transport),
                "transport references unknown or undispatched attempt",
            )
            _require(
                retained_accounting == accounting,
                "prompt/prefix/cache accounting differs from request bytes",
            )
            _require(
                ledger["study_status"]
                == (
                    "completed"
                    if completed and ledger["fatal_reason"] is None
                    else "partial"
                ),
                "study completion label mismatch",
            )
            return {
                "integrity": "PASS",
                "study_status": ledger["study_status"],
                "completed": completed and ledger["fatal_reason"] is None,
                "planned": 24,
                "started": len(started_ids),
                "accounting": accounting,
                "errors": [],
                "claim_ceiling": "local custody only; unsigned, no independent reproduction or efficacy claim",
            }
        finally:
            engine.dispose()


def verify(root: Path) -> dict[str, Any]:
    try:
        return _verify(root)
    except Exception as exc:  # noqa: BLE001 - untrusted evidence must return HOLD, never a traceback
        return {
            "integrity": "HOLD",
            "study_status": "unverified",
            "completed": False,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_root", type=Path)
    args = parser.parse_args()
    result = verify(args.evidence_root)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["integrity"] == "PASS" and result["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
