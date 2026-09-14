"""Trusted in-process graders. Study packs provide data, never executable grader code."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

import jsonschema
from adapters_v1.context_handoff.models import ContextPacket, RendererReceipt
from adapters_v1.context_handoff.render import RENDERER_DIGEST, render_context
from protocol_v1.canonical import canonical_json, sha256
from utils.json_extract import parse_json_lenient

from .models import EvaluationContext, GraderInstallation, GraderResult


def _json(output: str) -> Any | None:
    parsed = parse_json_lenient(output)
    return parsed.data if parsed.ok else None


def _at(value: Any, dotted_path: str) -> Any:
    current = value
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _at_json_pointer(value: Any, pointer: str) -> Any:
    current = value
    for token in pointer[1:].split("/"):
        part = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


class TrustedGrader(ABC):
    """Identity-bearing trusted local installation; never loaded from a StudyPack."""

    grader_id: str
    version: str
    digest: str


class DeterministicGrader(TrustedGrader):
    """Only explicit, trusted deterministic installations may be invoked."""

    @abstractmethod
    def evaluate(self, output: str, context: EvaluationContext) -> GraderResult: ...


class QualitativeGrader(TrustedGrader):
    """Trusted evaluator identity for externally observed, calibrated judgments."""


class TrustedGraderRegistry:
    """Local allowlist keyed by independently installed id, version, and artifact digest."""
    def __init__(self) -> None:
        self._graders: dict[tuple[str, str, str], TrustedGrader] = {}

    def install(
        self, grader: TrustedGrader, installation: GraderInstallation
    ) -> None:
        if not isinstance(grader, TrustedGrader):
            raise TypeError("only TrustedGrader instances may be installed")
        if (grader.grader_id, grader.version, grader.digest) != (
            installation.grader_id,
            installation.version,
            installation.digest,
        ):
            raise ValueError(
                "trusted installation id, version, and digest must match the grader"
            )
        identity = (installation.grader_id, installation.version, installation.digest)
        if identity in self._graders:
            raise ValueError(f"grader already installed: {installation.grader_id}")
        self._graders[identity] = grader

    register = install

    def resolve(self, installation: GraderInstallation) -> TrustedGrader:
        grader = self._graders.get(
            (installation.grader_id, installation.version, installation.digest)
        )
        if grader is None:
            raise LookupError(
                "trusted grader is not installed at exact identity: "
                f"{installation.grader_id}@{installation.version}#{installation.digest}"
            )
        if (grader.version, grader.digest) != (
            installation.version,
            installation.digest,
        ):
            raise ValueError(
                "installed grader no longer matches its trusted installation"
            )
        return grader


class SchemaGrader(DeterministicGrader):
    grader_id = "schema"
    version = "1"
    digest = "1" * 64

    def __init__(self, schema: Mapping[str, Any], metric_id: str = "schema") -> None:
        # Frozen protocol arrays are tuples internally; JSON Schema requires
        # JSON arrays at its public validation boundary.
        self.schema, self.metric_id = json.loads(canonical_json(schema)), metric_id

    def evaluate(self, output: str, context: EvaluationContext) -> GraderResult:
        del context
        value = _json(output)
        if value is None:
            return GraderResult(
                self.metric_id, 0.0, False, ("output is not valid JSON",)
            )
        try:
            jsonschema.validate(value, self.schema)
        except jsonschema.ValidationError as exc:
            return GraderResult(
                self.metric_id,
                0.0,
                False,
                (f"schema validation failed: {exc.message}",),
            )
        except jsonschema.SchemaError as exc:
            return GraderResult(
                self.metric_id, 0.0, False, (f"invalid trusted schema: {exc.message}",)
            )
        return GraderResult(self.metric_id, 1.0, True)


class ExactFieldGrader(DeterministicGrader):
    grader_id = "exact-field"
    version = "1"
    digest = "2" * 64

    def __init__(
        self, expected: Mapping[str, Any], metric_id: str = "exact-field"
    ) -> None:
        self.expected, self.metric_id = dict(expected), metric_id

    def evaluate(self, output: str, context: EvaluationContext) -> GraderResult:
        del context
        value = _json(output)
        if value is None:
            return GraderResult(
                self.metric_id, 0.0, False, ("output is not valid JSON",)
            )
        hits = sum(
            _at(value, path) == expected for path, expected in self.expected.items()
        )
        score = hits / len(self.expected) if self.expected else 1.0
        return GraderResult(
            self.metric_id,
            score,
            score == 1.0,
            tuple(
                path
                for path, expected in self.expected.items()
                if _at(value, path) != expected
            ),
        )


class ContextHandoffDeliveryGrader(DeterministicGrader):
    """Reconstruct delivery from frozen inputs; never trust an adapter label."""

    grader_id = "context-handoff-delivery"
    version = "1"
    digest = sha256({"grader": "context-handoff-delivery", "version": "1", "semantic_contract": "reconstruct-rendered-ollama-request-v1"})

    def __init__(self, *, task: str, packet: Mapping[str, Any], renderer_digest: str,
                 metric_id: str = "context-policy-delivery", failure_rule_id: str = "context-policy-delivery-mismatch") -> None:
        self.task = task
        self.packet = ContextPacket.model_validate(packet)
        self.renderer_digest = renderer_digest
        self.metric_id = metric_id
        self.failure_rule_id = failure_rule_id

    def evaluate(self, output: str, context: EvaluationContext) -> GraderResult:
        del output
        policy = context.factor_assignments.get("context_policy")
        receipt_raw = context.state_refs.get("context_renderer_receipt")
        frozen_request = context.state_refs.get("frozen_request_binding")
        observed_request_digest = context.state_refs.get("observed_request_digest")
        if policy not in {"isolated", "full_inherited", "curated"} or not isinstance(receipt_raw, Mapping) or not isinstance(frozen_request, Mapping) or not isinstance(observed_request_digest, str):
            return GraderResult(self.metric_id, 0.0, False, ("missing frozen factor-delivery evidence",), (self.failure_rule_id,))
        try:
            receipt = RendererReceipt.model_validate(dict(receipt_raw))
            prompt, expected = render_context(task=self.task, packet=self.packet, policy=policy)
        except (TypeError, ValueError):
            return GraderResult(self.metric_id, 0.0, False, ("invalid delivery receipt",), (self.failure_rule_id,))
        options = frozen_request.get("options")
        model = frozen_request.get("model")
        if not isinstance(options, Mapping) or not isinstance(model, str):
            return GraderResult(self.metric_id, 0.0, False, ("missing controller-bound request controls",), (self.failure_rule_id,))
        expected_request = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False, "think": False, "options": dict(options)}
        passed = self.renderer_digest == RENDERER_DIGEST and receipt.renderer_digest == self.renderer_digest and receipt == expected and observed_request_digest == sha256(expected_request)
        return GraderResult(self.metric_id, 1.0 if passed else 0.0, bool(passed), () if passed else ("independent context delivery reconstruction mismatch",), () if passed else (self.failure_rule_id,))


class SourceProvenanceGrader(DeterministicGrader):
    grader_id = "source-provenance"
    version = "1"
    digest = "3" * 64

    def __init__(
        self,
        claims_pointer: str,
        frozen_sources: Mapping[str, str],
        required_sources: Mapping[str, str],
        required_claim_sources: Mapping[str, tuple[str, ...]],
        metric_id: str = "source-provenance",
        unsupported_evidence_severe_rule_id: str | None = None,
    ) -> None:
        self.claims_pointer = claims_pointer
        self.frozen_sources = dict(frozen_sources)
        self.required_sources = dict(required_sources)
        self.required_claim_sources = {
            claim_id: tuple(source_ids)
            for claim_id, source_ids in required_claim_sources.items()
        }
        self.metric_id = metric_id
        self.unsupported_evidence_severe_rule_id = unsupported_evidence_severe_rule_id

    def evaluate(self, output: str, context: EvaluationContext) -> GraderResult:
        del context
        value = _json(output)
        if value is None:
            return GraderResult(self.metric_id, 0.0, False, ("output is not valid JSON",))
        claims = _at_json_pointer(value, self.claims_pointer)
        if not isinstance(claims, list):
            return GraderResult(
                self.metric_id,
                0.0,
                False,
                (f"claim evidence mapping must be an array at {self.claims_pointer}",),
            )

        diagnostics: list[str] = []
        cited_by_claim: dict[str, set[str]] = {}
        unsupported_evidence = False
        for entry in claims:
            if not isinstance(entry, Mapping):
                diagnostics.append("claim evidence entry must be an object")
                continue
            claim_id = entry.get("claim_id")
            citations = entry.get("evidence")
            if not isinstance(claim_id, str) or not claim_id:
                diagnostics.append("claim evidence entry has an invalid claim_id")
                continue
            if claim_id in cited_by_claim:
                diagnostics.append(f"duplicate claim evidence entry: {claim_id}")
                continue
            cited_by_claim[claim_id] = set()
            if not isinstance(citations, list) or not citations:
                diagnostics.append(f"claim {claim_id} has no evidence citations")
                continue
            for citation in citations:
                if not isinstance(citation, Mapping):
                    diagnostics.append(f"claim {claim_id} has a malformed evidence citation")
                    continue
                source_id = citation.get("source_id")
                content_hash = citation.get("content_hash")
                if not isinstance(source_id, str) or not isinstance(content_hash, str):
                    diagnostics.append(f"claim {claim_id} has a malformed evidence citation")
                    continue
                frozen_hash = self.frozen_sources.get(source_id)
                if frozen_hash is None:
                    diagnostics.append(f"claim {claim_id} references unknown evidence source: {source_id}")
                    unsupported_evidence = True
                    continue
                if content_hash != frozen_hash:
                    diagnostics.append(f"claim {claim_id} evidence hash mismatch: {source_id}")
                    unsupported_evidence = True
                    continue
                cited_by_claim[claim_id].add(source_id)

        cited_sources = set().union(*cited_by_claim.values()) if cited_by_claim else set()
        diagnostics.extend(
            f"required evidence source is not cited: {source_id}"
            for source_id in self.required_sources
            if source_id not in cited_sources
        )
        diagnostics.extend(
            f"required claim/source pair is missing: {claim_id}/{source_id}"
            for claim_id, source_ids in self.required_claim_sources.items()
            for source_id in source_ids
            if source_id not in cited_by_claim.get(claim_id, set())
        )
        severe = (
            (self.unsupported_evidence_severe_rule_id,)
            if unsupported_evidence and self.unsupported_evidence_severe_rule_id
            else ()
        )
        return GraderResult(
            self.metric_id, 1.0 if not diagnostics else 0.0, not diagnostics, tuple(diagnostics), severe
        )


class ForbiddenTokenGrader(DeterministicGrader):
    grader_id = "forbidden-token"
    version = "1"
    digest = "4" * 64

    def __init__(
        self,
        forbidden_tokens: tuple[str, ...],
        metric_id: str = "forbidden-token",
        severe_rule_id: str | None = None,
    ) -> None:
        self.forbidden_tokens, self.metric_id, self.severe_rule_id = (
            forbidden_tokens,
            metric_id,
            severe_rule_id,
        )

    def evaluate(self, output: str, context: EvaluationContext) -> GraderResult:
        del context
        found = tuple(
            token
            for token in self.forbidden_tokens
            if token.casefold() in output.casefold()
        )
        severe = (self.severe_rule_id,) if found and self.severe_rule_id else ()
        return GraderResult(
            self.metric_id, 1.0 if not found else 0.0, not found, found, severe
        )


class StateOracleGrader(DeterministicGrader):
    grader_id = "state-oracle"
    version = "1"
    digest = "5" * 64

    def __init__(
        self,
        state_key: str,
        expected: Any,
        metric_id: str = "state-oracle",
        failure_rule_id: str = "state-oracle-failed",
    ) -> None:
        self.state_key, self.expected, self.metric_id, self.failure_rule_id = (
            state_key,
            expected,
            metric_id,
            failure_rule_id,
        )

    def evaluate(self, output: str, context: EvaluationContext) -> GraderResult:
        del output
        passed = context.state_refs.get(self.state_key) == self.expected
        return GraderResult(
            self.metric_id,
            1.0 if passed else 0.0,
            passed,
            () if passed else ("authoritative state does not match expected value",),
            () if passed else (self.failure_rule_id,),
        )


class ManipulationFidelityGrader(DeterministicGrader):
    grader_id = "manipulation-fidelity"
    version = "1"
    digest = "6" * 64

    def __init__(
        self,
        expected_assignments: Mapping[str, str | int | bool],
        metric_id: str = "manipulation-fidelity",
        failure_rule_id: str = "manipulation-fidelity-failed",
    ) -> None:
        self.expected_assignments, self.metric_id, self.failure_rule_id = (
            dict(expected_assignments),
            metric_id,
            failure_rule_id,
        )

    def evaluate(self, output: str, context: EvaluationContext) -> GraderResult:
        del output
        mismatches = tuple(
            key
            for key, value in self.expected_assignments.items()
            if context.factor_assignments.get(key) != value
        )
        return GraderResult(
            self.metric_id,
            1.0 if not mismatches else 0.0,
            not mismatches,
            mismatches,
            () if not mismatches else (self.failure_rule_id,),
        )
