#!/usr/bin/env python3
"""Run a bounded, synthetic-only local-runtime custody exercise.

The command owns only a private temporary Protocol-v1 database and publishes a
sanitized JSON export.  It does not make paid-provider requests and it never
promotes local runtime custody into a confirmatory or scaffold-effect claim.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select

from adapters_v1 import (
    AdapterRegistry,
    HarnessAdapter,
    lm_studio_endpoint_digest,
    ollama_endpoint_digest,
)
from artifacts_v1 import LocalArtifactStore
from evaluation_v1 import EvaluationWorker, TrustedGraderRegistry
from execution_v1 import DurableWorker
from persistence_v1 import ArenaRepository, create_persistence_engine, metadata
from persistence_v1.schema import artifacts
from protocol_v1 import GraderSpec
from protocol_v1.canonical import (
    canonical_configuration_hash,
    canonical_json,
    sha256,
    sha256_bytes,
)
from services_v1 import (
    AnalysisService,
    EvidenceService,
    ExecutionService,
    ProtocolRegistryService,
    build_adapter_registry_from_config,
)

_SHA_RE = re.compile(r"^[a-f0-9]{40}(?:[a-f0-9]{24})?$")
_MODEL_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,128}$")
_RUNTIME_KINDS = {"ollama": "ollama_local", "lm-studio": "lm_studio_local"}
_EVIDENCE_OUTPUT_ROOT = "outputs/local_runtime_evidence/"
_EXPECTED_SYNTHETIC_RESPONSE = {"result": "ok"}
_OLLAMA_SUMMARY_KEYS = frozenset(
    {
        "model",
        "created_at",
        "done",
        "done_reason",
        "total_duration",
        "load_duration",
        "prompt_eval_count",
        "prompt_eval_duration",
        "eval_count",
        "eval_duration",
        "message",
    }
)
_LM_STUDIO_SUMMARY_KEYS = frozenset({"model_instance_id", "output", "stats"})
_EXPORT_FILES = (
    "summary.json",
    "attempts.json",
    "evaluations.json",
    "events.json",
    "receipt.json",
    "receipt-verification.json",
    "artifact-digest-inventory.json",
)
_BLOCKED_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "bearer_token",
        "body",
        "chain_of_thought",
        "content",
        "credential",
        "credentials",
        "message",
        "password",
        "private_key",
        "raw",
        "raw_body",
        "raw_provider_body",
        "raw_response",
        "reasoning",
        "secret",
        "secrets",
        "thought",
        "thoughts",
    }
)
_ARTIFACT_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "bearer_token",
        "chain_of_thought",
        "credential",
        "credentials",
        "password",
        "private_key",
        "reasoning",
        "secret",
        "secrets",
        "thought",
        "thoughts",
        "thinking",
    }
)


class LocalRuntimeEvidenceError(RuntimeError):
    """A fail-closed, user-safe runner error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def analysis_config() -> dict[str, Any]:
    """Return the fixed analysis contract used by every local-runtime run."""
    return {
        "registered_factors": [],
        "primary_main_effects": [],
        "secondary_interactions": [],
        "gates": {
            "preregistered_design": True,
            "comparison_invariants_pass": True,
            "minimum_manipulation_fidelity": 0.95,
            "minimum_trace_completeness": 0.95,
            "require_evaluator_independence": True,
            "require_held_out_tasks": True,
            "external_fitter_receipt": None,
        },
        "options": {
            "pass_k": 2,
            "bootstrap_resamples": 10,
            "bootstrap_seed": 1,
            "minimum_clusters": 2,
        },
    }


def _validate_code_revision(value: str, *, repo_root: Path) -> str:
    if not _SHA_RE.fullmatch(value):
        raise LocalRuntimeEvidenceError(
            "invalid_code_revision", "--code-revision must be a full lowercase Git SHA (40 or 64 hex characters)."
        )
    try:
        head = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            check=True,
            capture_output=True,
        ).stdout.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError, subprocess.CalledProcessError) as exc:
        raise LocalRuntimeEvidenceError(
            "checkout_unavailable", "Unable to verify the runner checkout before provider calls."
        ) from exc
    if value != head:
        raise LocalRuntimeEvidenceError(
            "code_revision_mismatch", "--code-revision must exactly match the executing checkout HEAD."
        )
    for entry in status.split("\0"):
        if not entry:
            continue
        if not entry.startswith("?? "):
            raise LocalRuntimeEvidenceError(
                "dirty_checkout", "Tracked or indexed checkout changes must be cleared before provider calls."
            )
        untracked_path = entry[3:]
        if untracked_path.startswith(_EVIDENCE_OUTPUT_ROOT):
            continue
        raise LocalRuntimeEvidenceError(
            "dirty_checkout", "Untracked files outside the evidence output root must be cleared before provider calls."
        )
    return head


def _validate_models(models: Sequence[str]) -> tuple[str, ...]:
    if not models:
        raise LocalRuntimeEvidenceError("model_required", "At least one --model is required.")
    if len(set(models)) != len(models):
        raise LocalRuntimeEvidenceError("duplicate_model", "Repeated --model values must be unique.")
    if any(not _MODEL_RE.fullmatch(model) or not model.strip() for model in models):
        raise LocalRuntimeEvidenceError("invalid_model", "Each model must be a bounded non-empty identifier.")
    return tuple(models)


def _validate_caps(
    *,
    max_attempts: int,
    max_tokens: int,
    max_output_tokens: int,
    max_context_tokens: int,
    max_wall_time_seconds: float,
    repetitions: int,
    model_count: int,
) -> None:
    expected = model_count * repetitions
    if max_attempts < 1 or expected > max_attempts:
        raise LocalRuntimeEvidenceError(
            "attempt_cap_exceeded", f"Expanded synthetic design requires {expected} attempts but --max-attempts is {max_attempts}."
        )
    if max_tokens < 1 or max_tokens > 1_000_000:
        raise LocalRuntimeEvidenceError("invalid_token_cap", "--max-tokens must be between 1 and 1000000.")
    if max_output_tokens < 1 or max_output_tokens > max_tokens:
        raise LocalRuntimeEvidenceError("invalid_output_cap", "--max-output-tokens must be positive and no greater than --max-tokens.")
    if max_context_tokens < 1 or max_context_tokens > 1_000_000:
        raise LocalRuntimeEvidenceError("invalid_context_cap", "--max-context-tokens must be between 1 and 1000000.")
    if not 0 < max_wall_time_seconds <= 86_400:
        raise LocalRuntimeEvidenceError("invalid_time_cap", "--max-wall-time-seconds must be greater than zero and at most 86400.")
    if repetitions < 1 or repetitions > 100:
        raise LocalRuntimeEvidenceError("invalid_repetitions", "--repetitions must be between 1 and 100.")
    if max_wall_time_seconds < expected:
        raise LocalRuntimeEvidenceError(
            "time_cap_exceeded", "--max-wall-time-seconds must leave at least one second per expanded attempt."
        )


def _runtime_metadata(runtime: str, endpoint: str) -> tuple[str, str]:
    try:
        if runtime == "ollama":
            return _RUNTIME_KINDS[runtime], ollama_endpoint_digest(endpoint)
        if runtime == "lm-studio":
            return _RUNTIME_KINDS[runtime], lm_studio_endpoint_digest(endpoint)
    except ValueError as exc:
        raise LocalRuntimeEvidenceError("invalid_endpoint", str(exc)) from None
    raise LocalRuntimeEvidenceError("invalid_runtime", "runtime must be ollama or lm-studio.")


def _validate_runtime_attestation(
    runtime: str,
    runtime_revision: str | None,
    model_artifact_digest: str | None,
) -> tuple[str | None, str | None]:
    if runtime == "lm-studio":
        if not runtime_revision or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", runtime_revision):
            raise LocalRuntimeEvidenceError("runtime_revision_required", "LM Studio requires a bounded --runtime-revision.")
        if not model_artifact_digest or not re.fullmatch(r"[a-f0-9]{64}", model_artifact_digest):
            raise LocalRuntimeEvidenceError("model_artifact_digest_required", "LM Studio requires a lowercase SHA-256 --model-artifact-digest.")
        return runtime_revision, model_artifact_digest
    if runtime_revision is not None or model_artifact_digest is not None:
        raise LocalRuntimeEvidenceError("runtime_attestation_ambiguous", "--runtime-revision and --model-artifact-digest are valid only with --runtime lm-studio.")
    return None, None


def _grader() -> dict[str, Any]:
    config = {"schema": {"type": "object"}}
    return {
        "grader_id": "json-object",
        "version": "1",
        "implementation": "schema",
        "kind": "deterministic",
        "config": config,
        "digest": GraderSpec.digest_for(
            grader_id="json-object",
            version="1",
            implementation="schema",
            kind="deterministic",
            config=config,
        ),
    }


def _pack(
    *,
    runtime_kind: str,
    adapter_id: str,
    adapter_digest: str,
    config_schema_hash: str,
    code_revision: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    grader = _grader()
    prompt = 'Synthetic local-runtime custody probe. Reply only with a JSON object: {"result":"ok"}.'
    hashes = {
        key: sha256({"schema": key, "version": "local-runtime-v1"})
        for key in ("input", "output", "trace")
    }
    scenarios = [
        {
            "scenario_id": f"local-runtime-{role}",
            "title": f"Synthetic local-runtime {role}",
            "task_family": "local-runtime-json",
            "prompt": prompt,
            "source_label": "synthetic",
            "data_classification": "synthetic",
            "control_role": role,
            "deterministic_metrics": [{"metric_id": "valid-json", "weight": 1.0, "oracle": "json-object"}],
            "reference_solution": {
                "reference_id": "synthetic-json-object",
                "artifact_hash": sha256({"reference": {"result": "ok"}}),
                "solvability_proof": "The synthetic prompt explicitly requests a single JSON object.",
            },
            "output_contract": {
                "schema_hash": sha256(grader["config"]["schema"]),
                "format": "json",
                "description": "A JSON object only.",
            },
            "final_state_oracle": {
                "oracle_id": "synthetic-no-state-change",
                "kind": "exact_match",
                "expected": {"state": "not-applicable"},
                "description": "No external state or tools are used by this synthetic prompt.",
            },
            "allowed_claims": ["exploratory local-runtime custody only"],
            "limitations": ["Synthetic prompt; not confirmatory and not a scaffold-effect comparison."],
        }
        for role in ("candidate", "positive", "negative", "anti_cheat")
    ]
    return {
        "study_pack_id": f"private-{runtime_kind}-evidence",
        "version": "2026.08.20.1",
        "title": f"Private exploratory {runtime_kind} local-runtime evidence",
        "description": "Bounded synthetic local-runtime custody exercise; not a public or confirmatory study.",
        "license_spdx": "MIT",
        "authors": [{"name": "Private operator"}],
        "compatibility": {"protocol_min": "1.0", "protocol_max": "1.0"},
        "allowed_claims": ["exploratory local-runtime custody only"],
        "limitations": ["Synthetic task; no confirmatory or scaffold-effect interpretation."],
        "preregistration": {
            "reference_uri": f"private://local-runtime/{runtime_kind}/2026-08-20",
            "content_hash": sha256({"study": runtime_kind, "revision": code_revision}),
        },
        "scenarios": scenarios,
        "graders": [grader],
        "harnesses": [
            {
                "harness_id": f"{runtime_kind}-harness",
                "version": "1",
                "adapter": "http",
                "adapter_identity": adapter_id,
                "adapter_digest": adapter_digest,
                "timeout_seconds": timeout_seconds,
                "retries": 0,
                "allowed_tools": [],
                "configuration": {},
                "effective_configuration_hash": canonical_configuration_hash({}),
                "capabilities": {"usage": True},
                "schema_hashes": {
                    "input_hash": hashes["input"],
                    "output_hash": hashes["output"],
                    "trace_hash": hashes["trace"],
                    "config_schema_hash": config_schema_hash,
                },
                "execution_mode": "local",
                "isolation": "none",
                "claim_eligibility": "live_provider",
            }
        ],
        "experiments": [
            {
                "experiment_id": f"template-{runtime_kind}-evidence",
                "study_pack_id": f"private-{runtime_kind}-evidence",
                "scenario_ids": ["local-runtime-candidate"],
                "harness_ids": [f"{runtime_kind}-harness"],
                "deterministic_weight": 1.0,
            }
        ],
    }


def _experiment(
    *,
    runtime: str,
    runtime_kind: str,
    endpoint_digest: str,
    models: tuple[str, ...],
    repetitions: int,
    max_attempts: int,
    max_tokens: int,
    max_output_tokens: int,
    max_context_tokens: int,
    max_wall_time_seconds: float,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    expected = len(models) * repetitions
    per_attempt_latency = max_wall_time_seconds / expected * 0.9
    if per_attempt_latency < 1.0:
        raise LocalRuntimeEvidenceError("time_cap_exceeded", "The wall-time cap is too small for the expanded design.")
    return {
        "experiment_id": f"private-{runtime_kind}-evidence-run",
        "study_pack_id": f"private-{runtime_kind}-evidence",
        "scenario_ids": ["local-runtime-candidate"],
        "harness_ids": [f"{runtime_kind}-harness"],
        "questions": ["Can a native bounded local runtime complete a synthetic durable attempt?"],
        "hypotheses": ["This exploratory exercise is not confirmatory and does not compare scaffolds."],
        "model_endpoints": [
            {
                "endpoint_id": f"{runtime}-loopback-{index}",
                "provider": runtime_kind,
                "model": model,
                "endpoint_digest": endpoint_digest,
            }
            for index, model in enumerate(models)
        ],
        "sampling": {"temperature": 0.0, "top_p": 1.0, "max_tokens": max_output_tokens},
        "repetitions": repetitions,
        "randomization_seed": 0,
        "budgets": {
            "max_attempts": 1,
            "max_cost_usd": 0.0,
            "max_latency_seconds": per_attempt_latency,
            "max_tokens": max_tokens,
            "max_tool_calls": 0,
            "max_context_tokens": max_context_tokens,
        },
        "aggregate_budget": {
            "max_total_cost_usd": 0.0,
            "max_total_tokens": expected * max_tokens,
            "max_total_tool_calls": 0,
            "max_wall_time_seconds": max_wall_time_seconds,
            "max_attempts": min(max_attempts, expected),
        },
        "deterministic_weight": 1.0,
        "primary_outcomes": ["valid-json"],
        "claim_ceiling": "exploratory local-runtime custody/integrity only; no correctness, confirmatory, or scaffold-effect claim",
        "claim_bearing": True,
        "owner_approval": "approved",
        "extensions": {"org.scaffold-arena.analysis-v1": analysis},
    }


def _provenance(
    *,
    runtime: str,
    endpoint_digest: str,
    models: tuple[str, ...],
    code_revision: str,
    max_tokens: int,
    max_context_tokens: int,
) -> dict[str, Any]:
    return {
        "code_revision": code_revision,
        "code_hash": sha256({"revision": code_revision, "component": "local-runtime-evidence-runner-v1"}),
        "runtime_image": "private-local-runtime-operator",
        "runtime_image_hash": sha256({"runtime": "private-local-runtime-operator"}),
        "environment_hash": sha256(
            {
                "runtime": runtime,
                "models": models,
                "endpoint_digest": endpoint_digest,
                "max_tokens": max_tokens,
                "max_context_tokens": max_context_tokens,
            }
        ),
        "prompt_hash": sha256({"prompt": "synthetic-local-runtime-custody-probe-v1"}),
        "context_hash": sha256({"context": "synthetic-only"}),
        "tool_hash": sha256({"tools": []}),
        "source_refs": [
            {"source_uri": "synthetic://scaffold-arena/local-runtime-custody-v1", "content_hash": sha256({"synthetic": True})}
        ],
        "captured_at": datetime.now(UTC).isoformat(),
    }


async def _registry(
    *,
    runtime: str,
    endpoint: str,
    code_revision: str,
    runtime_revision: str | None,
    model_artifact_digest: str | None,
    injected_adapter: HarnessAdapter | None,
) -> tuple[AdapterRegistry, str, str, str, str, HarnessAdapter | None]:
    runtime_kind, endpoint_digest = _runtime_metadata(runtime, endpoint)
    config_schema_hash = sha256({"adapter_runtime_config": f"{runtime_kind}-v1"})
    adapter_id = f"{runtime}-local"
    adapter_digest = sha256(
        {
            "adapter": runtime_kind,
            "revision": code_revision,
            "endpoint_digest": endpoint_digest,
            "config_schema_hash": config_schema_hash,
        }
    )
    runtime_revision, model_artifact_digest = _validate_runtime_attestation(
        runtime, runtime_revision, model_artifact_digest
    )
    if injected_adapter is not None:
        capabilities = await injected_adapter.describe_capabilities()
        if capabilities.adapter_kind != "http" or capabilities.claim_eligibility != "live_provider":
            raise LocalRuntimeEvidenceError("adapter_ineligible", "Injected test adapters must be HTTP/live-provider capable; no provider was called.")
        registry = AdapterRegistry()
        await registry.install_trusted(injected_adapter, capabilities.adapter_digest)
        return registry, capabilities.adapter_id, capabilities.adapter_digest, capabilities.config_schema_hash or config_schema_hash, endpoint_digest, injected_adapter
    try:
        registry = await build_adapter_registry_from_config(
            {
                "format": "scaffold-arena-adapter-runtime-v1",
                "adapters": [
                    {
                        "kind": runtime_kind,
                        "adapter_id": adapter_id,
                        "adapter_digest": adapter_digest,
                        "endpoint": endpoint,
                        "config_schema_hash": config_schema_hash,
                        **(
                            {
                                "runtime_revision": runtime_revision,
                                "model_artifact_digest": model_artifact_digest,
                            }
                            if runtime == "lm-studio"
                            else {}
                        ),
                    }
                ],
            }
        )
    except (TypeError, ValueError, OSError) as exc:
        raise LocalRuntimeEvidenceError("adapter_setup_failed", "The native local runtime adapter could not be configured.") from exc
    return registry, adapter_id, adapter_digest, config_schema_hash, endpoint_digest, None


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return value


def _sanitize(value: Any) -> Any:
    """Keep protocol metadata while rejecting provider bodies and reasoning."""
    if isinstance(value, Mapping):
        return {
            str(key): ("[REDACTED]" if str(key).lower() in _BLOCKED_KEYS else _sanitize(item))
            for key, item in value.items()
            if str(key).lower() not in {"content", "body", "raw_response", "reasoning", "thought", "thoughts"}
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, bytes):
        return {"sha256": sha256_bytes(value), "size_bytes": len(value)}
    return value


def _envelope_projection(envelope: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(envelope, Mapping):
        return None
    fields = (
        "attempt_id",
        "episode_id",
        "ordinal",
        "provider_model",
        "provider",
        "endpoint_id",
        "pinned_endpoint_digest",
        "harness_id",
        "factor_assignments",
        "budget",
        "provenance",
        "request_hash",
        "status",
        "queued_at",
        "started_at",
        "completed_at",
        "observed_provider_version",
        "observed_endpoint_digest",
        "response_hash",
    )
    return _sanitize({field: envelope.get(field) for field in fields if field in envelope})


def _result_projection(result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    fields = (
        "terminal_outcome",
        "response_hash",
        "failure_classification",
        "input_artifact_digest",
        "output_artifact_digest",
        "trace_artifact_digest",
        "state_oracle_artifact_digest",
        "manipulation_artifact_digest",
        "artifact_digests",
        "trace_complete",
        "manipulation_pass",
        "manipulation_detail",
        "cost_status",
        "cost_usd",
        "limitations",
        "usage",
        "terminal_envelope",
    )
    return _sanitize({field: result.get(field) for field in fields if field in result})


def _evaluation_projection(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    result = evaluation.get("result")
    projected = {
        field: evaluation.get(field)
        for field in (
            "id",
            "evaluator",
            "evaluator_version",
            "evaluator_digest",
            "result_hash",
            "result_artifact_digest",
            "input_artifact_digest",
            "output_artifact_digest",
            "trace_artifact_digest",
            "exclusion_state",
        )
        if field in evaluation
    }
    if isinstance(result, Mapping):
        projected["result"] = _sanitize(result)
    elif result is not None:
        projected["result_digest"] = sha256(result)
    return _sanitize(projected)


def _export_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    attempts: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []
    digests: set[str] = set()
    for row in rows:
        request = row.get("request_metadata")
        result = row.get("result_metadata")
        request_envelope = request.get("envelope") if isinstance(request, Mapping) else None
        jobs = row.get("jobs") if isinstance(row.get("jobs"), list) else []
        evaluations_raw = row.get("evaluations") if isinstance(row.get("evaluations"), list) else []
        attempt = {
            "attempt_id": row.get("attempt_id"),
            "scenario_id": row.get("scenario_id"),
            "attempt_ordinal": row.get("attempt_ordinal"),
            "status": row.get("status"),
            "request": _envelope_projection(request_envelope),
            "result": _result_projection(result),
            "jobs": [
                _sanitize(
                    {
                        field: job.get(field)
                        for field in ("id", "kind", "status", "attempt_count", "created_at", "available_at")
                        if field in job
                    }
                )
                for job in jobs
                if isinstance(job, Mapping)
            ],
        }
        attempts.append(attempt)
        for evaluation in evaluations_raw:
            if isinstance(evaluation, Mapping):
                evaluations.append({"attempt_id": row.get("attempt_id"), **_evaluation_projection(evaluation)})
        for candidate in (result or {},):
            if isinstance(candidate, Mapping):
                for key, value in candidate.items():
                    if "artifact_digest" in str(key) and isinstance(value, str) and len(value) == 64:
                        digests.add(value)
                    if key == "artifact_digests" and isinstance(value, list):
                        digests.update(item for item in value if isinstance(item, str) and len(item) == 64)
        for evaluation in evaluations_raw:
            if isinstance(evaluation, Mapping):
                digests.update(
                    str(evaluation[key])
                    for key in ("result_artifact_digest", "input_artifact_digest", "output_artifact_digest", "trace_artifact_digest")
                    if isinstance(evaluation.get(key), str) and len(str(evaluation[key])) == 64
                )
    return attempts, evaluations, digests


def _events_export(events: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        _sanitize(
            {
                "cursor": event.cursor,
                "event_id": event.event_id,
                "attempt_id": event.attempt_id,
                "attempt_sequence": event.attempt_sequence,
                "event_type": event.event_type,
                "payload": dict(event.payload),
                "created_at": event.created_at,
            }
        )
        for event in events
    ]


def _artifact_inventory(repository: ArenaRepository, digests: set[str]) -> list[dict[str, Any]]:
    if not digests:
        return []
    with repository.engine.connect() as connection:
        rows = connection.execute(select(artifacts).where(artifacts.c.digest.in_(sorted(digests)))).mappings().all()
    return [
        {
            "sha256": row["digest"],
            "path": f"artifacts/{row['digest']}",
            "size_bytes": row["size_bytes"],
            "media_type": row["media_type"],
            "metadata": {
                key: value
                for key, value in (row.get("metadata_json") or {}).items()
                if key in {"kind", "artifact_role", "format", "manifest_hash", "report_digest"}
            },
            "content": "withheld",
        }
        for row in sorted(rows, key=lambda item: str(item["digest"]))
    ]


def _privacy_guard(value: Any, *, artifact_digest: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _ARTIFACT_SENSITIVE_KEYS:
                raise LocalRuntimeEvidenceError(
                    "artifact_privacy_hold",
                    f"Referenced artifact {artifact_digest} contains a prohibited privacy field; output is withheld.",
                )
            _privacy_guard(item, artifact_digest=artifact_digest)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _privacy_guard(item, artifact_digest=artifact_digest)
    elif isinstance(value, str):
        lowered = value.lower()
        if any(
            marker in lowered
            for marker in (
                "chain of thought",
                "private reasoning",
                "api_key=",
                "authorization:",
                "bearer ",
                "client_secret",
                "private_key",
            )
        ):
            raise LocalRuntimeEvidenceError(
                "artifact_privacy_hold",
                f"Referenced artifact {artifact_digest} contains prohibited privacy text; output is withheld.",
            )


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _parse_exact_synthetic_response(content: bytes, *, artifact_digest: str) -> None:
    try:
        payload = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, ValueError) as exc:
        raise LocalRuntimeEvidenceError(
            "synthetic_response_hold",
            f"Assistant output artifact {artifact_digest} is not the exact synthetic response; output is withheld.",
        ) from exc
    if type(payload) is not dict or payload != _EXPECTED_SYNTHETIC_RESPONSE:
        raise LocalRuntimeEvidenceError(
            "synthetic_response_hold",
            f"Assistant output artifact {artifact_digest} is not the exact synthetic response; output is withheld.",
        )


def _validate_provider_response_summary(content: bytes, *, artifact_digest: str) -> None:
    try:
        payload = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, ValueError):
        return
    if not isinstance(payload, Mapping) or "raw_response_sha256" not in payload:
        return
    if (
        set(payload) != {"response", "raw_response_sha256"}
        or not isinstance(payload["response"], Mapping)
        or not isinstance(payload["raw_response_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", payload["raw_response_sha256"])
    ):
        raise LocalRuntimeEvidenceError(
            "provider_summary_hold",
            f"Provider response summary {artifact_digest} is not structurally admissible; output is withheld.",
        )
    response = payload["response"]
    message = response.get("message")
    output = response.get("output")
    if message is not None:
        if (
            output is not None
            or not set(response).issubset(_OLLAMA_SUMMARY_KEYS)
            or not isinstance(message, Mapping)
            or set(message) != {"role", "content"}
            or message.get("role") != "assistant"
            or not isinstance(message.get("content"), str)
        ):
            raise LocalRuntimeEvidenceError(
                "provider_summary_hold",
                f"Provider response summary {artifact_digest} is not structurally admissible; output is withheld.",
            )
        _parse_exact_synthetic_response(message["content"].encode("utf-8"), artifact_digest=artifact_digest)
        return
    if (
        message is not None
        or not set(response).issubset(_LM_STUDIO_SUMMARY_KEYS)
        or not isinstance(output, list)
        or len(output) != 1
        or not isinstance(output[0], Mapping)
    ):
        raise LocalRuntimeEvidenceError(
            "provider_summary_hold",
            f"Provider response summary {artifact_digest} is not structurally admissible; output is withheld.",
        )
    item = output[0]
    if set(item) != {"type", "content"} or item.get("type") != "message" or not isinstance(item.get("content"), str):
        raise LocalRuntimeEvidenceError(
            "provider_summary_hold",
            f"Provider response summary {artifact_digest} is not structurally admissible; output is withheld.",
        )
    _parse_exact_synthetic_response(item["content"].encode("utf-8"), artifact_digest=artifact_digest)


def _validate_synthetic_output_artifacts(
    store: LocalArtifactStore, rows: Sequence[Mapping[str, Any]]
) -> None:
    for row in rows:
        result = row.get("result_metadata")
        digest = result.get("output_artifact_digest") if isinstance(result, Mapping) else None
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise LocalRuntimeEvidenceError(
                "synthetic_response_hold", "A completed attempt lacks a bound assistant output artifact; output is withheld."
            )
        _parse_exact_synthetic_response(store.get_bytes(digest), artifact_digest=digest)


def _artifact_payloads(store: LocalArtifactStore, inventory: Sequence[Mapping[str, Any]]) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for item in inventory:
        digest = str(item["sha256"])
        content = store.get_bytes(digest)
        if sha256_bytes(content) != digest:
            raise LocalRuntimeEvidenceError("artifact_integrity_hold", "A referenced artifact failed its content digest check.")
        try:
            _privacy_guard(json.loads(content), artifact_digest=digest)
        except UnicodeDecodeError:
            _privacy_guard(content.decode("utf-8", errors="replace"), artifact_digest=digest)
        except ValueError:
            _privacy_guard(content.decode("utf-8", errors="replace"), artifact_digest=digest)
        _validate_provider_response_summary(content, artifact_digest=digest)
        payloads[f"artifacts/{digest}"] = content
    return payloads


def _write_export(
    staging: Path,
    files: Mapping[str, Any],
    artifact_payloads: Mapping[str, bytes],
    artifact_inventory: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    digests: dict[str, str] = {}
    for name in _EXPORT_FILES:
        payload = canonical_json(files[name])
        (staging / name).write_bytes(payload)
        digests[name] = sha256_bytes(payload)
    artifact_root = staging / "artifacts"
    artifact_root.mkdir()
    for path, payload in sorted(artifact_payloads.items()):
        target = staging / path
        target.write_bytes(payload)
        digest = path.rsplit("/", 1)[-1]
        if sha256_bytes(payload) != digest:
            raise LocalRuntimeEvidenceError("artifact_integrity_hold", "An exported artifact path does not match its digest.")
        digests[path] = digest
    manifest = {
        "format": "scaffold-arena-local-runtime-evidence-export-v1",
        "files": [
            {
                "path": name,
                "sha256": digests[name],
                **next(
                    (
                        {
                            "media_type": item["media_type"],
                            "size_bytes": item["size_bytes"],
                        }
                        for item in artifact_inventory
                        if item.get("path") == name
                    ),
                    {},
                ),
            }
            for name in (*_EXPORT_FILES, *sorted(artifact_payloads))
        ],
        "bundle_hash": sha256({"files": digests}),
        "integrity_not_truth": True,
        "claim_ceiling": "exploratory local-runtime custody/integrity only; no correctness, confirmatory, or scaffold-effect claim",
    }
    (staging / "bundle-manifest.json").write_bytes(canonical_json(manifest))
    return manifest


async def run_local_runtime_evidence(
    *,
    runtime: str,
    endpoint: str,
    models: Sequence[str],
    output: str | Path,
    code_revision: str,
    max_attempts: int = 1,
    max_tokens: int = 512,
    max_output_tokens: int = 256,
    max_context_tokens: int = 1024,
    max_wall_time_seconds: float = 120.0,
    repetitions: int = 1,
    runtime_revision: str | None = None,
    model_artifact_digest: str | None = None,
    injected_adapter: HarnessAdapter | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Execute and export one bounded local-runtime custody exercise.

    ``injected_adapter`` is intentionally test-only dependency injection.  It
    must expose the same live-provider capability contract as a native adapter;
    a mock transport can therefore exercise this complete path without a
    provider process or network call.
    """
    output_path = Path(output).expanduser()
    if output_path.exists():
        raise LocalRuntimeEvidenceError("output_collision", "Refusing to overwrite an existing --output directory.")
    models_tuple = _validate_models(models)
    _validate_caps(
        max_attempts=max_attempts,
        max_tokens=max_tokens,
        max_output_tokens=max_output_tokens,
        max_context_tokens=max_context_tokens,
        max_wall_time_seconds=max_wall_time_seconds,
        repetitions=repetitions,
        model_count=len(models_tuple),
    )
    runtime_kind, endpoint_digest = _runtime_metadata(runtime, endpoint)
    runtime_revision, model_artifact_digest = _validate_runtime_attestation(
        runtime, runtime_revision, model_artifact_digest
    )
    checkout_root = (repo_root or ROOT).resolve()
    code_revision = _validate_code_revision(code_revision, repo_root=checkout_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="scaffold-arena-local-runtime-") as temporary:
        temporary_root = Path(temporary)
        engine = create_persistence_engine(f"sqlite:///{temporary_root / 'arena.db'}")
        metadata.create_all(engine)
        repository = ArenaRepository(engine)
        project_id = "private-local-runtime"
        repository.create_project("Private exploratory local-runtime evidence", project_id=project_id)
        store = LocalArtifactStore(temporary_root / "artifacts")
        adapter: HarnessAdapter | None = injected_adapter
        try:
            registry, adapter_id, adapter_digest, config_schema_hash, endpoint_digest, adapter = await _registry(
                runtime=runtime,
                endpoint=endpoint,
                code_revision=code_revision,
                runtime_revision=runtime_revision,
                model_artifact_digest=model_artifact_digest,
                injected_adapter=injected_adapter,
            )
            analysis = analysis_config()
            pack = _pack(
                runtime_kind=runtime_kind,
                adapter_id=adapter_id,
                adapter_digest=adapter_digest,
                config_schema_hash=config_schema_hash,
                code_revision=code_revision,
                timeout_seconds=max(
                    1,
                    int(max_wall_time_seconds / (len(models_tuple) * repetitions) * 0.9),
                ),
            )
            experiment = _experiment(
                runtime=runtime,
                runtime_kind=runtime_kind,
                endpoint_digest=endpoint_digest,
                models=models_tuple,
                repetitions=repetitions,
                max_attempts=max_attempts,
                max_tokens=max_tokens,
                max_output_tokens=max_output_tokens,
                max_context_tokens=max_context_tokens,
                max_wall_time_seconds=max_wall_time_seconds,
                analysis=analysis,
            )
            protocol = ProtocolRegistryService(repository, store, adapter_registry=registry, personal_project_id=project_id)
            imported = protocol.import_pack(canonical_json(pack), "application/json", project_id=project_id)
            created = protocol.create_experiment(experiment, project_id=project_id)
            frozen = protocol.freeze(created["experiment_id"], project_id=project_id)
            preflight = protocol.preflight(created["experiment_id"], project_id=project_id)
            if preflight["verdict"] != "PASS":
                raise LocalRuntimeEvidenceError("preflight_hold", "Synthetic local-runtime preflight did not PASS; no evidence receipt was derived.")
            expected_attempts = int(preflight["expected_attempts"])
            provenance = _provenance(
                runtime=runtime,
                endpoint_digest=endpoint_digest,
                models=models_tuple,
                code_revision=code_revision,
                max_tokens=max_tokens,
                max_context_tokens=max_context_tokens,
            )
            execution_service = ExecutionService(repository, store, adapter_registry=registry, personal_project_id=project_id)
            request_key = f"private-{runtime_kind}-execution-v1"
            execution = execution_service.create_execution(
                created["experiment_id"], provenance, project_id=project_id, request_key=request_key
            )
            started = monotonic()
            worker_results: list[dict[str, Any]] = []
            worker = DurableWorker(repository, registry, store, project_id=project_id)
            while True:
                remaining = max_wall_time_seconds - (monotonic() - started)
                if remaining <= 0:
                    raise LocalRuntimeEvidenceError("wall_time_exceeded", "The durable worker exceeded the configured wall-time cap.")
                result = await asyncio.wait_for(
                    worker.run_once("local-runtime-attempt-worker", lease_seconds=max(2.0, min(300.0, remaining))),
                    timeout=remaining,
                )
                if result is None:
                    break
                worker_results.append({"status": result.status, "detail": result.detail})
                if result.status != "completed":
                    raise LocalRuntimeEvidenceError("attempt_hold", f"A durable local-runtime attempt did not complete ({result.detail or 'no detail'}); output is withheld.")
                if len(worker_results) > max_attempts:
                    raise LocalRuntimeEvidenceError("attempt_cap_exceeded", "The durable worker exceeded the configured attempt cap.")
            if len(worker_results) != expected_attempts:
                raise LocalRuntimeEvidenceError("attempt_count_mismatch", "Durable workers did not complete the frozen synthetic design.")

            evaluation_results: list[dict[str, Any]] = []
            evaluator = EvaluationWorker(repository, store, TrustedGraderRegistry(), project_id=project_id)
            while True:
                remaining = max_wall_time_seconds - (monotonic() - started)
                if remaining <= 0:
                    raise LocalRuntimeEvidenceError("wall_time_exceeded", "The evaluator exceeded the configured wall-time cap.")
                result = evaluator.run_once("local-runtime-independent-evaluator", lease_seconds=max(2.0, min(60.0, remaining)))
                if result is None:
                    break
                evaluation_results.append({"status": result.status, "detail": result.detail})
                if result.status != "completed":
                    raise LocalRuntimeEvidenceError("evaluation_hold", "A separate evaluator did not complete; output is withheld.")
            if len(evaluation_results) != expected_attempts:
                raise LocalRuntimeEvidenceError("evaluation_count_mismatch", "Separate evaluators did not cover the frozen synthetic design.")

            execution_view = execution_service.execution(execution["execution_id"], project_id=project_id)
            if execution_view["status"] != "completed":
                raise LocalRuntimeEvidenceError("execution_hold", "The durable execution is not completed; output is withheld.")
            _, terminal_rows, _ = repository.derived_execution_evidence_source(
                project_id, execution["execution_id"]
            )
            terminal_outcomes = [
                row.get("result_metadata", {}).get("terminal_outcome")
                if isinstance(row.get("result_metadata"), Mapping)
                else None
                for row in terminal_rows
            ]
            if len(terminal_outcomes) != expected_attempts or any(
                outcome != "completed" for outcome in terminal_outcomes
            ):
                raise LocalRuntimeEvidenceError(
                    "attempt_terminal_hold",
                    "At least one durable attempt lacks a completed evidence-bearing result; output is withheld.",
                )
            analysis_result = AnalysisService(repository, store, personal_project_id=project_id).analyze(
                {
                    "experiment_id": created["experiment_id"],
                    "execution_id": execution["execution_id"],
                    "analysis_config": analysis,
                },
                project_id=project_id,
            )
            evidence = EvidenceService(repository, store, personal_project_id=project_id)
            receipt = evidence.derive_execution_receipt(
                {"execution_id": execution["execution_id"], "request_key": f"private-{runtime_kind}-receipt-v1"},
                project_id=project_id,
            )
            verification = evidence.verify_receipt(receipt["receipt_id"], project_id=project_id)
            if receipt.get("evidence_type") != "derived_local_live" or receipt.get("evidence_class") != "local_live" or not verification.get("verified"):
                raise LocalRuntimeEvidenceError("receipt_hold", "The derived local-live receipt did not pass fresh verification; output is withheld.")

            binding, rows, _prices = repository.derived_execution_evidence_source(project_id, execution["execution_id"])
            if binding is None:
                raise LocalRuntimeEvidenceError("evidence_source_missing", "The durable evidence source could not be re-read.")
            _validate_synthetic_output_artifacts(store, rows)
            attempt_exports, evaluation_exports, digest_set = _export_rows(rows)
            digest_set.add(imported["content_digest"])
            digest_set.add(analysis_result["artifact_digest"])
            digest_set.update(item["sha256"] for item in receipt.get("artifacts", []) if isinstance(item, Mapping) and isinstance(item.get("sha256"), str))
            events, terminal_status = execution_service.events(execution["execution_id"], project_id=project_id, cursor=None)
            if terminal_status != "completed":
                raise LocalRuntimeEvidenceError("event_hold", "The execution event stream did not terminate as completed.")
            inventory = _artifact_inventory(repository, digest_set)
            if {item["sha256"] for item in inventory} != digest_set:
                raise LocalRuntimeEvidenceError("artifact_inventory_hold", "Not every exported artifact digest is registered durably.")
            summary = {
                "format": "scaffold-arena-local-runtime-evidence-summary-v1",
                "status": "COMPLETE_LOCAL_EXPLORATORY_CUSTODY",
                "runtime": runtime,
                "runtime_registry_kind": runtime_kind,
                "endpoint_identity_digest": endpoint_digest,
                "models": list(models_tuple),
                "code_revision": code_revision,
                "runtime_revision": runtime_revision,
                "model_artifact_digest": model_artifact_digest,
                "synthetic_only": True,
                "no_tools": True,
                "paid_cost_usd": 0.0,
                "energy_status": "unknown",
                "expected_attempts": expected_attempts,
                "attempts_completed": len(worker_results),
                "evaluations_completed": len(evaluation_results),
                "study_pack_digest": imported["content_digest"],
                "freeze_hash": frozen["freeze_hash"],
                "preflight": {"verdict": preflight["verdict"], "expected_attempts": preflight["expected_attempts"]},
                "execution": {"execution_id": execution["execution_id"], "status": execution_view["status"]},
                "analysis": {
                    "verdict": analysis_result["verdict"],
                    "report_digest": analysis_result["report_digest"],
                    "claim_ceiling": analysis_result["claim_ceiling"],
                },
                "receipt": {
                    "receipt_id": receipt["receipt_id"],
                    "evidence_type": receipt["evidence_type"],
                    "evidence_class": receipt["evidence_class"],
                    "claim_ceiling": receipt["claim_ceiling"],
                },
                "claim_boundary": "Exploratory local-runtime custody/integrity only; never confirmatory and never a scaffold-effect claim.",
            }
            files: dict[str, Any] = {
                "summary.json": summary,
                "attempts.json": attempt_exports,
                "evaluations.json": evaluation_exports,
                "events.json": _events_export(events),
                "receipt.json": receipt,
                "receipt-verification.json": verification,
                "artifact-digest-inventory.json": inventory,
            }
            with tempfile.TemporaryDirectory(prefix="scaffold-arena-local-export-") as export_tmp:
                staging = Path(export_tmp)
                artifact_payloads = _artifact_payloads(store, inventory)
                _write_export(staging, files, artifact_payloads, inventory)
                try:
                    output_path.mkdir(parents=False, exist_ok=False)
                except FileExistsError as exc:
                    raise LocalRuntimeEvidenceError("output_collision", "Refusing to overwrite an existing --output directory.") from exc
                for source in sorted(staging.iterdir()):
                    if source.is_dir():
                        shutil.copytree(source, output_path / source.name)
                    else:
                        shutil.copy2(source, output_path / source.name)
            return {
                "output": str(output_path),
                "summary": summary,
                "manifest": _write_export_manifest_summary(files, artifact_payloads),
            }
        finally:
            close = getattr(adapter, "aclose", None)
            if callable(close):
                await close()
            engine.dispose()


def _write_export_manifest_summary(files: Mapping[str, Any], artifact_payloads: Mapping[str, bytes]) -> dict[str, Any]:
    return {
        "format": "scaffold-arena-local-runtime-evidence-export-v1",
        "files": {
            **{name: sha256_bytes(canonical_json(value)) for name, value in files.items()},
            **{name: sha256_bytes(value) for name, value in artifact_payloads.items()},
        },
        "integrity_not_truth": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=("ollama", "lm-studio"), required=True)
    parser.add_argument("--endpoint", required=True, help="Literal loopback native API base (/api or /api/v1).")
    parser.add_argument("--model", action="append", required=True, help="Repeatable local model identifier.")
    parser.add_argument("--output", type=Path, required=True, help="A new export directory; existing paths are rejected.")
    parser.add_argument("--code-revision", required=True, help="Full lowercase Git SHA (40 or 64 hex characters).")
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--max-output-tokens", type=int, default=256)
    parser.add_argument("--max-context-tokens", type=int, default=1024)
    parser.add_argument("--max-wall-time-seconds", type=float, default=120.0)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument(
        "--runtime-revision",
        help="Required operator-attested LM Studio runtime revision; invalid for Ollama.",
    )
    parser.add_argument(
        "--model-artifact-digest",
        help="Required operator-attested LM Studio model-file SHA-256; invalid for Ollama.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(
            run_local_runtime_evidence(
                runtime=args.runtime,
                endpoint=args.endpoint,
                models=args.model,
                output=args.output,
                code_revision=args.code_revision,
                max_attempts=args.max_attempts,
                max_tokens=args.max_tokens,
                max_output_tokens=args.max_output_tokens,
                max_context_tokens=args.max_context_tokens,
                max_wall_time_seconds=args.max_wall_time_seconds,
                repetitions=args.repetitions,
                runtime_revision=args.runtime_revision,
                model_artifact_digest=args.model_artifact_digest,
            )
        )
    except LocalRuntimeEvidenceError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 2
    print(canonical_json(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
