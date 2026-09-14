"""Shared fail-closed boundary for pinned external harness installations."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from protocol_v1.canonical import canonical_json, sha256
from protocol_v1.models import HarnessSpec, TraceEvent

from ..base import HarnessAdapter
from ..models import (
    AdapterCapabilities,
    AdapterHealth,
    ArtifactRef,
    AttemptInput,
    PreparedAttempt,
    ResultBundle,
    validate_events_for_attempt,
    validate_result_for_attempt,
)
from ..preflight import preflight


@dataclass(frozen=True)
class UpstreamRelease:
    name: str
    source_url: str
    version: str
    commit: str
    maturity: str

    def identity(self) -> dict[str, str]:
        return {
            "name": self.name,
            "source_url": self.source_url,
            "version": self.version,
            "commit": self.commit,
            "maturity": self.maturity,
        }


@dataclass(frozen=True)
class ExternalOciEvidence:
    """An external container assertion; this wrapper does not construct containers."""

    image: str
    image_digest: str
    evidence_uri: str
    evidence_hash: str

    def __post_init__(self) -> None:
        if not self.image or not self.evidence_uri:
            raise ValueError("OCI image and evidence URI are required")
        for value in (self.image_digest, self.evidence_hash):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError("OCI evidence digests must be lowercase SHA-256")

    def binding(self) -> dict[str, str]:
        return {
            "image": self.image,
            "image_digest": self.image_digest,
            "evidence_uri": self.evidence_uri,
            "evidence_hash": self.evidence_hash,
        }


class ExternalHarnessTransport(Protocol):
    """A separately configured bridge; wrappers never launch upstream software."""

    async def healthcheck(self) -> bool: ...
    async def prepare(self, input: AttemptInput, *, timeout_seconds: int) -> str: ...
    async def execute(self, opaque_handle: str) -> ResultBundle: ...
    async def events(self, opaque_handle: str) -> tuple[TraceEvent, ...]: ...
    async def artifacts(self, opaque_handle: str) -> tuple[ArtifactRef, ...]: ...
    async def cancel(self, opaque_handle: str) -> None: ...
    async def cleanup(self, opaque_handle: str) -> None: ...


IdentityProbe = Callable[[], Awaitable[Mapping[str, str] | None]]
OciEvidenceProbe = Callable[[ExternalOciEvidence], Awaitable[bool]]


class PinnedExternalAdapter(HarnessAdapter):
    """Validates identity and protocol binding before delegating to an injected bridge."""

    def __init__(
        self,
        *,
        adapter_id: str,
        release: UpstreamRelease,
        identity_probe: IdentityProbe | None = None,
        transport: ExternalHarnessTransport | None = None,
        oci_evidence: ExternalOciEvidence | None = None,
        oci_evidence_probe: OciEvidenceProbe | None = None,
        preview_only: bool = False,
    ) -> None:
        self.release = release
        self.oci_evidence = oci_evidence
        self._identity_probe = identity_probe
        self._transport = transport
        self._oci_evidence_probe = oci_evidence_probe
        self._preview_only = preview_only
        digest = sha256({"release": release.identity(), "oci_evidence": oci_evidence.binding() if oci_evidence else None})
        verified_oci_configured = oci_evidence is not None and oci_evidence_probe is not None
        claim_eligibility = "protocol_only" if preview_only or not verified_oci_configured else "live_provider"
        isolation = ("remote_sandbox",) if verified_oci_configured else ("none", "process")
        self._capabilities = AdapterCapabilities(
            adapter_id=adapter_id,
            adapter_digest=digest,
            adapter_kind="cli",
            supported_isolation=isolation,
            claim_eligibility=claim_eligibility,
            supports_cancellation=transport is not None,
            supports_artifacts=transport is not None,
        )
        self._attempts: dict[str, tuple[AttemptInput, str]] = {}
        self._cancelled: set[str] = set()
        self._cleaned: set[str] = set()

    @property
    def adapter_digest(self) -> str:
        return self._capabilities.adapter_digest

    async def describe_capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def healthcheck(self) -> AdapterHealth:
        if self._identity_probe is None:
            return self._health(False, "upstream identity probe is not configured")
        try:
            observed = await self._identity_probe()
            identity_matches = observed is not None and dict(observed) == self.release.identity()
        except Exception:  # noqa: BLE001 - diagnostics intentionally do not expose upstream output
            return self._health(False, "upstream identity probe failed")
        if not identity_matches:
            return self._health(False, "pinned upstream identity is unavailable or mismatched")
        if self._transport is None:
            return self._health(False, "pinned upstream bridge is not configured")
        if self.oci_evidence is not None and self._oci_evidence_probe is not None:
            try:
                evidence_verified = await self._oci_evidence_probe(self.oci_evidence)
            except Exception:  # noqa: BLE001 - diagnostics intentionally redact verifier details
                return self._health(False, "OCI isolation evidence verification failed")
            if not evidence_verified:
                return self._health(False, "OCI isolation evidence is unavailable or mismatched")
        try:
            bridge_healthy = await self._transport.healthcheck()
        except Exception:  # noqa: BLE001 - diagnostics intentionally redact transport details
            return self._health(False, "pinned upstream bridge healthcheck failed")
        return self._health(bool(bridge_healthy), "pinned upstream identity and bridge verified" if bridge_healthy else "pinned upstream bridge is unhealthy")

    async def prepare_attempt(self, harness: HarnessSpec, input: AttemptInput) -> PreparedAttempt:
        input = AttemptInput.model_validate_json(canonical_json(input.model_dump(mode="json")))
        preflight(self._capabilities, harness, input)
        health = await self.healthcheck()
        if not health.healthy:
            raise ValueError("pinned external harness is unavailable")
        if self._transport is None:
            raise ValueError("pinned external harness bridge is unavailable")
        if self.oci_evidence is None and harness.claim_eligibility not in {"fixture_only", "protocol_only"}:
            raise ValueError("unsandboxed external harness is ineligible beyond protocol-only claims")
        if self._preview_only and harness.claim_eligibility not in {"fixture_only", "protocol_only"}:
            raise ValueError("experimental DeepSeek preview is protocol-only")
        opaque_handle = await self._transport.prepare(input, timeout_seconds=harness.timeout_seconds)
        if not opaque_handle:
            raise ValueError("external harness bridge returned an empty prepared handle")
        attempt_id = input.attempt.attempt_id
        self._attempts[attempt_id] = (input, opaque_handle)
        return PreparedAttempt(
            attempt_id=attempt_id,
            adapter_id=self._capabilities.adapter_id,
            prepared_at=datetime.now(UTC),
            timeout_seconds=harness.timeout_seconds,
            opaque_handle=opaque_handle,
            input_digest=sha256(input.model_dump(mode="json")),
        )

    async def execute_attempt(self, prepared: PreparedAttempt) -> ResultBundle:
        input, opaque_handle = self._attempt(prepared)
        if self._transport is None:
            raise ValueError("pinned external harness bridge is unavailable")
        if prepared.attempt_id in self._cancelled:
            raise ValueError("cancelled external attempt cannot be executed")
        result = await self._transport.execute(opaque_handle)
        return validate_result_for_attempt(result, input.attempt)

    async def stream_events(self, prepared: PreparedAttempt) -> AsyncIterator[TraceEvent]:
        input, opaque_handle = self._attempt(prepared)
        if self._transport is None:
            raise ValueError("pinned external harness bridge is unavailable")
        for event in validate_events_for_attempt(await self._transport.events(opaque_handle), input.attempt):
            yield event

    async def collect_artifacts(self, prepared: PreparedAttempt) -> tuple[ArtifactRef, ...]:
        self._attempt(prepared)
        if self._transport is None:
            raise ValueError("pinned external harness bridge is unavailable")
        return await self._transport.artifacts(prepared.opaque_handle)

    async def cancel_attempt(self, prepared: PreparedAttempt) -> None:
        self._attempt(prepared)
        if prepared.attempt_id in self._cancelled:
            return
        if self._transport is not None:
            await self._transport.cancel(prepared.opaque_handle)
        self._cancelled.add(prepared.attempt_id)

    async def cleanup_attempt(self, prepared: PreparedAttempt) -> None:
        self._attempt(prepared)
        if prepared.attempt_id in self._cleaned:
            return
        await self.cancel_attempt(prepared)
        if self._transport is not None:
            await self._transport.cleanup(prepared.opaque_handle)
        self._cleaned.add(prepared.attempt_id)

    def _attempt(self, prepared: PreparedAttempt) -> tuple[AttemptInput, str]:
        if prepared.adapter_id != self._capabilities.adapter_id:
            raise ValueError("prepared attempt is not owned by this adapter")
        try:
            input, opaque_handle = self._attempts[prepared.attempt_id]
        except KeyError as exc:
            raise ValueError("prepared attempt is not owned by this adapter") from exc
        if prepared.opaque_handle != opaque_handle or prepared.input_digest != sha256(input.model_dump(mode="json")):
            raise ValueError("prepared external attempt binding mismatch")
        return input, opaque_handle

    @staticmethod
    def _health(healthy: bool, detail: str) -> AdapterHealth:
        return AdapterHealth(healthy=healthy, checked_at=datetime.now(UTC), detail=detail)
