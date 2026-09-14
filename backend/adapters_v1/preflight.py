"""Fail-closed compatibility checks before an adapter is allowed to execute."""

from __future__ import annotations

from protocol_v1.canonical import sha256
from protocol_v1.models import HarnessSpec

from .models import AdapterCapabilities, AttemptInput


class AdapterPreflightError(ValueError):
    pass


def preflight(capabilities: AdapterCapabilities, harness: HarnessSpec, input: AttemptInput) -> None:
    attempt = input.attempt
    if attempt.harness_id != harness.harness_id:
        raise AdapterPreflightError("attempt harness_id does not match harness spec")
    if harness.adapter != capabilities.adapter_kind:
        raise AdapterPreflightError("harness adapter kind does not match installed adapter")
    if harness.adapter_identity != capabilities.adapter_id:
        raise AdapterPreflightError("harness must name the trusted adapter identity")
    if harness.adapter_digest != capabilities.adapter_digest:
        raise AdapterPreflightError("harness adapter digest does not match trusted installation")
    if harness.isolation not in capabilities.supported_isolation:
        raise AdapterPreflightError("requested isolation is unsupported")
    eligibility = ("fixture_only", "protocol_only", "live_provider", "externally_validated")
    if eligibility.index(harness.claim_eligibility) > eligibility.index(capabilities.claim_eligibility):
        raise AdapterPreflightError("adapter cannot support requested claim eligibility")
    for name in type(harness.capabilities).model_fields:
        if getattr(harness.capabilities, name) and not getattr(capabilities.capabilities, name):
            raise AdapterPreflightError(f"required capability unavailable: {name}")
    if harness.timeout_seconds > attempt.budget.max_latency_seconds:
        raise AdapterPreflightError("harness timeout exceeds attempt latency budget")
    actual_config_hash = sha256(harness.configuration)
    if harness.effective_configuration_hash is not None and harness.effective_configuration_hash != actual_config_hash:
        raise AdapterPreflightError("harness configuration hash mismatch")
    requested_schema_hash = harness.schema_hashes.config_schema_hash
    if capabilities.config_schema_hash is not None:
        if requested_schema_hash != capabilities.config_schema_hash:
            raise AdapterPreflightError("adapter configuration schema hash is missing or mismatched")
    elif requested_schema_hash is not None:
        raise AdapterPreflightError("adapter does not certify a configuration schema")
