"""Executable-control layer for the local OpenAI-compatible adapter."""

from __future__ import annotations

from typing import Any

import httpx

from protocol_v1.canonical import canonical_json, sha256_bytes

from ..controls import (
    CORE_CONTROL_IDS,
    AppliedControls,
    ControlApplication,
    execution_controls_for,
)
from ..models import ArtifactRef, AttemptInput, PreparedAttempt, ResultBundle
from .adapter import OpenAICompatibleAdapter as _BaseOpenAICompatibleAdapter

_GENERATION_CONTROLS = frozenset(
    {"temperature", "top_p", "max_output_tokens", "seed"}
)
_RUNTIME_CONTROLS = frozenset(
    {"timeout_seconds", "max_tool_calls", "max_context_tokens", "max_attempts"}
)


class OpenAICompatibleAdapter(_BaseOpenAICompatibleAdapter):
    """Apply frozen generation controls and emit a digest-bound receipt."""

    def _request(self, bound: AttemptInput) -> dict[str, Any]:
        controls = execution_controls_for(bound)
        return {
            "model": bound.attempt.provider_model,
            "messages": [{"role": "user", "content": bound.scenario.prompt}],
            "stream": False,
            "temperature": controls.temperature,
            "top_p": controls.top_p,
            "max_tokens": controls.max_output_tokens,
            "seed": controls.seed,
        }

    def _complete_response(
        self,
        prepared: PreparedAttempt,
        response: httpx.Response,
    ) -> ResultBundle:
        result = super()._complete_response(prepared, response)
        bound, _ = self._attempt(prepared)
        controls = execution_controls_for(bound)
        values = controls.control_values()
        applications: list[ControlApplication] = []
        for control_id in CORE_CONTROL_IDS:
            value = values[control_id]
            if control_id in _GENERATION_CONTROLS:
                applications.append(
                    ControlApplication(
                        control_id=control_id,
                        status="applied",
                        requested_value=value,
                        observed_value=value,
                    )
                )
            elif control_id in _RUNTIME_CONTROLS:
                applications.append(
                    ControlApplication(
                        control_id=control_id,
                        status="bound",
                        requested_value=value,
                        observed_value=value,
                        detail=(
                            "Bound by the immutable AttemptInput and enforced by "
                            "the Arena worker/adapter lifecycle rather than the "
                            "provider generation payload."
                        ),
                    )
                )
        receipt = AppliedControls.bind(
            tuple(applications),
            provider_request_id=response.headers.get("x-request-id"),
        )
        receipt_bytes = canonical_json(receipt.model_dump(mode="json"))
        receipt_artifact = ArtifactRef(
            artifact_id="applied-controls",
            media_type="application/vnd.scaffold-arena.applied-controls+json",
            sha256=sha256_bytes(receipt_bytes),
            content=receipt_bytes,
        )
        artifacts = tuple(result.artifacts) + (receipt_artifact,)
        # Keep collect_artifacts() backward-compatible. The worker persists both
        # result.artifacts and collected artifacts, so the receipt remains a
        # durable first-class artifact without duplicating the collection view.
        return result.model_copy(
            update={
                "applied_controls": receipt,
                "artifacts": artifacts,
            }
        )
