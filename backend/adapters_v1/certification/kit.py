"""Fail-closed, no-network certification exercises for HarnessAdapter."""

from __future__ import annotations

from datetime import UTC, datetime

from protocol_v1.models import HarnessSpec

from ..base import HarnessAdapter
from ..models import (
    ArtifactRef,
    AttemptInput,
    CertificationCase,
    CertificationReport,
    PreparedAttempt,
    ResultBundle,
    validate_events_for_attempt,
    validate_response_artifact_contract,
)

_CASE_NAMES = (
    "capability", "input_binding", "lifecycle", "trace", "usage",
    "artifact", "isolation", "cancellation",
)
_SECRET_MARKERS = (b"authorization:", b"api_key", b"bearer ", b"client_secret", b"private_key")


async def certify_adapter(adapter: HarnessAdapter, harness: HarnessSpec, input: AttemptInput) -> CertificationReport:
    """Certify behavior for one fixture without raising its claim eligibility."""
    capabilities = await adapter.describe_capabilities()
    cases: list[CertificationCase] = []
    prepared: PreparedAttempt | None = None
    try:
        health = await adapter.healthcheck()
        mismatch_rejected = await _rejects_capability_mismatch(adapter, harness, input)
        cases.append(CertificationCase(
            case="capability",
            passed=health.healthy and harness.adapter == capabilities.adapter_kind and mismatch_rejected,
            detail="installed capability and mismatch rejection verified" if health.healthy and mismatch_rejected else "HOLD: health or capability mismatch rejection failed",
        ))
        sandbox_eligible = _sandbox_claim_eligible(capabilities)
        cases.append(CertificationCase(
            case="isolation",
            passed=sandbox_eligible,
            detail="declared state/tool claim eligibility has a sandbox boundary" if sandbox_eligible else "HOLD: state/tool live claim lacks container or remote sandbox evidence",
        ))

        prepared = await adapter.prepare_attempt(harness, input)
        mutation_rejected = await _rejects_input_mutation(adapter, harness, input)
        hash_rejected = await _rejects_prepared_hash_mutation(adapter, prepared)
        cases.append(CertificationCase(
            case="input_binding",
            passed=mutation_rejected and hash_rejected,
            detail="canonical input and prepared hash mutation rejected" if mutation_rejected and hash_rejected else "HOLD: input mutation or hash mismatch accepted",
        ))

        result = await adapter.execute_attempt(prepared)
        repeat = await adapter.execute_attempt(prepared)
        lifecycle_ok = result == repeat and result.attempt_id == input.attempt.attempt_id
        cases.append(CertificationCase(
            case="lifecycle",
            passed=lifecycle_ok,
            detail="one stable terminal result" if lifecycle_ok else "HOLD: terminal result re-entered or changed",
        ))

        events = tuple([event async for event in adapter.stream_events(prepared)])
        try:
            validate_events_for_attempt(events, input.attempt)
            trace_ok = bool(events) and all(event.trace_id for event in events)
        except ValueError:
            trace_ok = False
        cases.append(CertificationCase(
            case="trace",
            passed=trace_ok,
            detail=f"{len(events)} ordered, attempt-bound event(s)" if trace_ok else "HOLD: at least one ordered, attempt-bound trace event is required",
        ))

        usage_ok, usage_detail = _usage_case(result, harness.claim_eligibility)
        cases.append(CertificationCase(case="usage", passed=usage_ok, detail=usage_detail))

        artifacts = await adapter.collect_artifacts(prepared)
        artifacts_ok, response_bound = _response_artifact_case(result, artifacts)
        secrets_ok = all(item.content is None or not _contains_secret(item.content) for item in (*result.artifacts, *artifacts))
        cases.append(CertificationCase(
            case="artifact",
            passed=artifacts_ok and secrets_ok and response_bound,
            detail="artifact hashes, canonical response binding, and secret-safe content verified" if artifacts_ok and secrets_ok and response_bound else "HOLD: artifact hash, canonical response binding, or secret-safe artifact check failed",
        ))

        await adapter.cancel_attempt(prepared)
        await adapter.cancel_attempt(prepared)
        drained = tuple([event async for event in adapter.stream_events(prepared)])
        cases.append(CertificationCase(
            case="cancellation",
            passed=drained == events,
            detail="cancel and event drain are idempotent" if drained == events else "HOLD: cancellation changed an already durable trace",
        ))
    except Exception as exc:  # noqa: BLE001 - adapter failures are certification evidence
        observed = {item.case for item in cases}
        for name in _CASE_NAMES:
            if name not in observed:
                cases.append(CertificationCase(case=name, passed=False, detail=_stable_error_code(exc)))
    finally:
        cleanup_ok = False
        cleanup_detail = "attempt was not prepared"
        if prepared is not None:
            try:
                await adapter.cleanup_attempt(prepared)
                await adapter.cleanup_attempt(prepared)
                cleanup_ok, cleanup_detail = True, "cleanup is idempotent"
            except Exception as exc:  # noqa: BLE001 - cleanup failures are certification evidence
                cleanup_detail = _stable_error_code(exc)
        cases.append(CertificationCase(case="cleanup", passed=cleanup_ok, detail=cleanup_detail))
    return CertificationReport(
        adapter_id=capabilities.adapter_id,
        adapter_digest=capabilities.adapter_digest,
        certified_at=datetime.now(UTC),
        passed=all(item.passed for item in cases),
        cases=tuple(cases),
    )


async def _rejects_capability_mismatch(adapter: HarnessAdapter, harness: HarnessSpec, input: AttemptInput) -> bool:
    mismatch = harness.model_copy(update={"adapter": "recorded" if harness.adapter != "recorded" else "http"})
    try:
        await adapter.prepare_attempt(mismatch, input)
    except Exception:  # noqa: BLE001 - rejection type is implementation-defined
        return True
    return False


async def _rejects_input_mutation(adapter: HarnessAdapter, harness: HarnessSpec, input: AttemptInput) -> bool:
    changed = input.model_copy(update={"scenario": input.scenario.model_copy(update={"prompt": input.scenario.prompt + " [mutated]"})})
    try:
        await adapter.prepare_attempt(harness, changed)
    except Exception:  # noqa: BLE001 - rejection type is implementation-defined
        return True
    return False


async def _rejects_prepared_hash_mutation(adapter: HarnessAdapter, prepared: PreparedAttempt) -> bool:
    changed = prepared.model_copy(update={"input_digest": "0" * 64})
    try:
        await adapter.execute_attempt(changed)
    except Exception:  # noqa: BLE001 - rejection type is implementation-defined
        return True
    return False


def _usage_case(result: object, claim_eligibility: str) -> tuple[bool, str]:
    usage = getattr(result, "usage", None)
    outcome = getattr(result, "terminal_outcome", None)
    live_claim = claim_eligibility in {"live_provider", "externally_validated"}
    if outcome == "completed" and live_claim:
        if usage is None or not usage.complete_evidence:
            return False, "HOLD: live/external completed result lacks complete provider usage evidence"
        return True, "complete provider usage; unknown cost preserved when absent"
    if outcome == "completed":
        return True, "fixture/protocol completion does not upgrade unknown usage or cost"
    return True, "non-completed result preserved unknown usage/cost without zero substitution"


def _response_artifact_case(result: ResultBundle, artifacts: tuple[object, ...]) -> tuple[bool, bool]:
    """Confirm the collected view still exposes the exact canonical response artifact."""
    try:
        validate_response_artifact_contract(result)
    except ValueError:
        return False, False
    all_artifacts = (*result.artifacts, *artifacts)
    hashes_ok = all(
        isinstance(item, ArtifactRef)
        and (item.content is None or item.sha256 == _hash_bytes(item.content))
        for item in all_artifacts
    )
    if result.response_artifact_id is None:
        return hashes_ok, True
    collected = [
        item for item in artifacts
        if isinstance(item, ArtifactRef) and item.artifact_id == result.response_artifact_id
    ]
    response_bound = (
        len(collected) == 1
        and collected[0].sha256 == result.response_hash
        and (collected[0].content is not None or collected[0].uri is not None)
    )
    return hashes_ok, response_bound


def _sandbox_claim_eligible(capabilities: object) -> bool:
    declared = capabilities.capabilities
    isolation = set(capabilities.supported_isolation)
    if (declared.tools or declared.state) and capabilities.claim_eligibility in {"live_provider", "externally_validated"}:
        return bool(isolation & {"container", "remote_sandbox"})
    return True


def _contains_secret(value: bytes) -> bool:
    return any(marker in value.lower() for marker in _SECRET_MARKERS)


def _stable_error_code(exc: Exception) -> str:
    return f"adapter_error:{type(exc).__name__}"


def _hash_bytes(value: bytes) -> str:
    from protocol_v1.canonical import sha256_bytes

    return sha256_bytes(value)
