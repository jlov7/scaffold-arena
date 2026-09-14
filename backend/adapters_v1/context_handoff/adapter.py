"""The one closed Ollama adapter permitted for the frozen context study."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from config.models import LOCAL_OLLAMA_CONTEXT_HANDOFF_PROFILE
from protocol_v1.canonical import canonical_json, sha256, sha256_bytes
from protocol_v1.models import HarnessSpec

from ..controlled_models import AttemptInput, ResultBundle
from ..models import ArtifactRef, PreparedAttempt
from ..ollama.adapter import OllamaAdapter, OllamaEvidenceHold
from .models import (
    CONTEXT_HANDOFF_NAMESPACE,
    EXPECTED_MODEL,
    EXPECTED_MODEL_DIGEST,
    EXPECTED_OLLAMA_VERSION,
    ContextPacket,
    FrozenRuntimeBinding,
    RendererReceipt,
)
from .render import RENDERER_DIGEST, render_context

CONTEXT_HANDOFF_ADAPTER_ID = "context-handoff-ollama"
CONTEXT_HANDOFF_CONFIG_SCHEMA_HASH = sha256(
    {
        "adapter": CONTEXT_HANDOFF_ADAPTER_ID,
        "schema": "v1",
        "runtime": FrozenRuntimeBinding().model_dump(mode="json"),
        "renderer_digest": RENDERER_DIGEST,
        "request": {
            "temperature": 0,
            "top_p": 1,
            "num_ctx": 4096,
            "num_predict": 256,
            "tools": 0,
        },
    }
)
CONTEXT_HANDOFF_ADAPTER_DIGEST = sha256(
    {
        "adapter": CONTEXT_HANDOFF_ADAPTER_ID,
        "config_schema_hash": CONTEXT_HANDOFF_CONFIG_SCHEMA_HASH,
        "renderer_digest": RENDERER_DIGEST,
        "context_policy_contract": "v1",
        "trace_schema": "factor-fidelity-v1",
    }
)


class ContextHandoffOllamaAdapter(OllamaAdapter):
    """A prompt-only transformation with per-attempt frozen runtime identity checks."""

    def __init__(
        self,
        *,
        endpoint: str,
        adapter_id: str = CONTEXT_HANDOFF_ADAPTER_ID,
        adapter_digest: str = CONTEXT_HANDOFF_ADAPTER_DIGEST,
        config_schema_hash: str = CONTEXT_HANDOFF_CONFIG_SCHEMA_HASH,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if (adapter_id, adapter_digest, config_schema_hash) != (
            CONTEXT_HANDOFF_ADAPTER_ID,
            CONTEXT_HANDOFF_ADAPTER_DIGEST,
            CONTEXT_HANDOFF_CONFIG_SCHEMA_HASH,
        ):
            raise ValueError(
                "context-handoff adapter identity is closed and hash-bound"
            )
        super().__init__(
            adapter_id=adapter_id,
            adapter_digest=adapter_digest,
            endpoint=endpoint,
            client=client,
            config_schema_hash=config_schema_hash,
        )
        self._receipts: dict[str, tuple[str, RendererReceipt]] = {}
        self.evidence_sink: Callable[[str, str, str, str, bytes], None] | None = None
        self._capture_attempt_id: str | None = None

    async def prepare_attempt(
        self, harness: HarnessSpec, input: AttemptInput
    ) -> PreparedAttempt:
        self._capture_attempt_id = input.attempt.attempt_id
        if (
            input.attempt.provider != "ollama"
            or input.attempt.provider_model != EXPECTED_MODEL
        ):
            raise ValueError(
                "context-handoff adapter accepts only the frozen local Ollama model"
            )
        if (
            harness.adapter_digest != CONTEXT_HANDOFF_ADAPTER_DIGEST
            or harness.schema_hashes.config_schema_hash
            != CONTEXT_HANDOFF_CONFIG_SCHEMA_HASH
        ):
            raise ValueError(
                "harness must bind the closed context-handoff adapter identity"
            )
        raw = input.scenario.extensions.get(CONTEXT_HANDOFF_NAMESPACE)
        if not isinstance(raw, dict):
            raise ValueError("scenario is missing frozen context-handoff packet")  # noqa: TRY004 - protocol admission failure
        allowed = {"packet", "runtime"}
        if set(raw) != allowed:
            raise ValueError("context-handoff scenario extension has unknown fields")
        packet = ContextPacket.model_validate(raw["packet"])
        runtime = FrozenRuntimeBinding.model_validate(raw["runtime"])
        if runtime.model != EXPECTED_MODEL:
            raise ValueError(
                "scenario runtime binding does not match the closed adapter"
            )
        policy = input.attempt.factor_assignments.get("context_policy")
        if policy not in {"isolated", "full_inherited", "curated"}:
            raise ValueError(
                "attempt must contain exactly one context_policy factor assignment"
            )
        prompt, receipt = render_context(
            task=input.scenario.prompt, packet=packet, policy=policy
        )
        prepared = await super().prepare_attempt(harness, input)
        self._receipts[prepared.attempt_id] = (prompt, receipt)
        return prepared

    def _observe_transport(
        self, method: str, url: str, phase: str, content: bytes
    ) -> None:
        if self.evidence_sink is not None and self._capture_attempt_id is not None:
            self.evidence_sink(self._capture_attempt_id, method, url, phase, content)

    async def execute_attempt(self, prepared: PreparedAttempt) -> ResultBundle:
        result = await super().execute_attempt(prepared)
        # Preserve typed provider holds and observed controls even when the
        # durable job completed successfully by recording a failed attempt.
        content = canonical_json(result.model_dump(mode="json", exclude={"artifacts"}))
        receipt = ArtifactRef(
            artifact_id="context-terminal-receipt",
            media_type="application/json",
            sha256=sha256_bytes(content),
            content=content,
        )
        artifacts = self._artifacts.get(prepared.attempt_id, ()) + (receipt,)
        self._artifacts[prepared.attempt_id] = artifacts
        return result.model_copy(update={"artifacts": artifacts})

    def _request(self, bound: AttemptInput) -> dict[str, Any]:
        request = super()._request(bound)
        stored = self._receipts.get(bound.attempt.attempt_id)
        if stored is None:
            raise OllamaEvidenceHold("context rendering receipt is missing")
        request["messages"] = [{"role": "user", "content": stored[0]}]
        return request

    async def _runtime_identity(
        self, model: str, max_context_tokens: int
    ) -> dict[str, Any]:
        identity = await super()._runtime_identity(model, max_context_tokens)
        if identity.get("ollama_version") != EXPECTED_OLLAMA_VERSION:
            raise OllamaEvidenceHold("HOLD_RUNTIME_VERSION_MISMATCH")
        if identity.get("model_digest") != EXPECTED_MODEL_DIGEST:
            raise OllamaEvidenceHold("HOLD_MODEL_DIGEST_MISMATCH")
        return identity

    async def _complete_response(
        self,
        prepared: PreparedAttempt,
        payload: object,
        raw_response: bytes,
        before_identity: dict[str, Any],
    ) -> ResultBundle:
        result = await super()._complete_response(
            prepared, payload, raw_response, before_identity
        )
        usage = result.usage
        if usage is not None:
            usage = usage.model_copy(
                update={
                    "billing_profile": LOCAL_OLLAMA_CONTEXT_HANDOFF_PROFILE,
                    "cached_input_tokens": None,
                    "service_tier": None,
                    "tool_billing_usd": None,
                }
            )
        prompt, receipt = self._receipts[prepared.attempt_id]
        receipt_bytes = canonical_json(receipt.model_dump(mode="json"))
        prompt_bytes = prompt.encode("utf-8")
        base_artifacts = tuple(
            ArtifactRef(
                artifact_id="provider-usage",
                media_type=item.media_type,
                sha256=sha256_bytes(canonical_json(usage.model_dump(mode="json"))),
                content=canonical_json(usage.model_dump(mode="json")),
            )
            if item.artifact_id == "provider-usage" and usage is not None
            else item
            for item in result.artifacts
        )
        artifacts = base_artifacts + (
            ArtifactRef(
                artifact_id="context-renderer-receipt",
                media_type="application/vnd.scaffold-arena.context-renderer-receipt+json",
                sha256=sha256_bytes(receipt_bytes),
                content=receipt_bytes,
            ),
            ArtifactRef(
                artifact_id="rendered-context-prompt",
                media_type="text/plain; charset=utf-8",
                sha256=sha256_bytes(prompt_bytes),
                content=prompt_bytes,
            ),
        )
        self._artifacts[prepared.attempt_id] = artifacts
        self._append(
            prepared,
            "harness",
            "state",
            {
                "event": "factor_fidelity",
                "factor_id": "context_policy",
                "context_policy": receipt.context_policy,
                "passed": True,
                "compute_context_matched": True,
                "renderer_digest": receipt.renderer_digest,
                "rendered_prompt_hash": receipt.prompt_hash,
                "included_segment_ids": list(receipt.included_segment_ids),
                "excluded_segment_ids": list(receipt.excluded_segment_ids),
            },
        )
        if (
            usage is not None
            and usage.input_tokens is not None
            and usage.input_tokens > 3840
        ):
            return self._result(
                prepared.attempt_id,
                "incomplete",
                "HOLD_CONTEXT_BUDGET_EXCEEDED",
                usage=usage,
                artifacts=artifacts,
                failure_classification="permanent_protocol",
                applied_controls=result.applied_controls,
            )
        if (
            usage is not None
            and usage.output_tokens is not None
            and usage.output_tokens > 256
        ):
            return self._result(
                prepared.attempt_id,
                "incomplete",
                "HOLD_OUTPUT_BUDGET_EXCEEDED",
                usage=usage,
                artifacts=artifacts,
                failure_classification="permanent_protocol",
                applied_controls=result.applied_controls,
            )
        return result.model_copy(update={"usage": usage, "artifacts": artifacts})

    async def cleanup_attempt(self, prepared: PreparedAttempt) -> None:
        self._receipts.pop(prepared.attempt_id, None)
        await super().cleanup_attempt(prepared)
        self._capture_attempt_id = None
