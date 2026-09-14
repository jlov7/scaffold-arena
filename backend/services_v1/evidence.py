"""Durable evidence custody services; integrity verification never promotes correctness."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from adapters_v1 import AttemptInput
from artifacts_v1 import ArtifactStore
from evidence_v1 import (
    EvidenceClass,
    EvidenceManifest,
    EvidenceReceipt,
    ExternalIndependenceAttestation,
    ReproductionReceipt,
    create_receipt,
    verify_evidence,
)
from persistence_v1 import ArenaRepository, ImmutableReceiptConflict
from persistence_v1.schema import artifacts, evidence_receipts, projects
from protocol_v1 import AttemptEnvelope, HarnessSpec
from protocol_v1.canonical import canonical_json, sha256, sha256_bytes


class EvidenceError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


_ADMISSION_CEILINGS = {
    EvidenceClass.FIXTURE: "fixture custody/integrity only; no correctness claim",
    EvidenceClass.LOCAL_LIVE: "local-live custody/integrity only; no correctness claim",
}
_REDACTION = "artifact content is withheld; hashes are custody metadata only"
_GENERIC_EVIDENCE_TYPES = frozenset({
    "fixture", "local_live", "reproduction", "cross_model", "human_calibration", "independent_reproduction",
})
_DERIVED_FIXTURE_KIND = "derived_fixture"
_DERIVED_LOCAL_LIVE_KIND = "derived_local_live"
_DIGEST_KEYS = frozenset({
    "input_artifact_digest", "output_artifact_digest", "trace_artifact_digest",
    "state_oracle_artifact_digest", "manipulation_artifact_digest",
})


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


class EvidenceService:
    def __init__(self, repository: ArenaRepository, artifact_store: ArtifactStore, *, personal_project_id: str | None = None) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.personal_project_id = personal_project_id

    def resolve_project(self, project_id: str | None) -> str:
        resolved = project_id or self.personal_project_id
        if not resolved:
            raise EvidenceError("project_context_required", "An explicit project context is required.")
        with self.repository.engine.connect() as conn:
            known = conn.execute(select(projects.c.id).where(projects.c.id == resolved)).scalar_one_or_none()
        if known is None:
            raise EvidenceError("unknown_project", "The supplied project does not exist.", status_code=404)
        return resolved

    def record_receipt(
        self,
        payload: Mapping[str, Any],
        *,
        project_id: str | None,
    ) -> dict[str, Any]:
        """Store a fully bound receipt after re-reading every artifact once at admission."""
        project_id = self.resolve_project(project_id)
        if set(payload) != {"manifest", "receipt", "evidence_type", "execution_id"}:
            raise EvidenceError("invalid_evidence_receipt", "Use exactly manifest, receipt, evidence_type, and execution_id.")
        evidence_type = payload.get("evidence_type")
        if evidence_type not in _GENERIC_EVIDENCE_TYPES:
            raise EvidenceError("invalid_evidence_type", "The evidence type is not recognized.")
        if evidence_type != "fixture":
            raise EvidenceError(
                "evidence_admission_hold",
                "Only fixture custody receipts may be admitted by generic upload; this class requires a dedicated durable workflow.",
                status_code=409,
            )
        if payload.get("execution_id") is not None and not isinstance(payload.get("execution_id"), str):
            raise EvidenceError("invalid_evidence_receipt", "execution_id must be a string or null.")
        try:
            manifest = EvidenceManifest.model_validate_json(canonical_json(payload["manifest"]))
            receipt = EvidenceReceipt.model_validate_json(canonical_json(payload["receipt"]))
        except (KeyError, TypeError, ValidationError) as exc:
            raise EvidenceError("invalid_evidence_receipt", "The evidence receipt payload is malformed.") from exc
        if manifest.evidence_class is not EvidenceClass.FIXTURE:
            raise EvidenceError(
                "evidence_class_mismatch",
                "The evidence type is not compatible with the manifest evidence class.",
                status_code=409,
            )
        service_ceiling = _ADMISSION_CEILINGS[EvidenceClass.FIXTURE]
        if manifest.claim_ceiling != service_ceiling:
            raise EvidenceError(
                "claim_ceiling_mismatch",
                "The manifest claim ceiling does not match the service-owned admission ceiling.",
                status_code=409,
            )
        execution_id = payload["execution_id"]
        if execution_id is not None:
            self._require_execution_binding(project_id, execution_id, manifest)
        registered = self._registered_artifacts(manifest.artifact_hashes)
        verification = verify_evidence(
            receipt,
            manifest,
            self.artifact_store,
            evidence_type=str(payload["evidence_type"]),
            verifier_id="evidence-admission-v1",
            verifier_digest=sha256({"service": "evidence-admission-v1"}),
            registered_artifacts=registered,
        )
        if not verification.verified:
            raise EvidenceError("receipt_integrity_invalid", "The receipt or its stored artifacts cannot be verified.", status_code=409)
        try:
            replay = self.repository.create_evidence_receipt(
                project_id,
                receipt_id=receipt.receipt_id,
                receipt_hash=receipt.receipt_hash,
                manifest_hash=receipt.manifest_hash,
                manifest_json=manifest.model_dump(mode="json"),
                artifact_hashes=receipt.artifact_hashes,
                evidence_type=str(payload["evidence_type"]),
                claim_ceiling=service_ceiling,
                execution_id=payload["execution_id"],
            )
        except ImmutableReceiptConflict as exc:
            raise EvidenceError("receipt_conflict", "The receipt identifier is already bound to different evidence.", status_code=409) from exc
        except ValueError as exc:
            raise EvidenceError("receipt_rejected", "The evidence receipt cannot be stored in this project.", status_code=409) from exc
        return {**self.get_receipt(receipt.receipt_id, project_id=project_id), "idempotent_replay": replay}

    def derive_execution_receipt(
        self, payload: Mapping[str, Any], *, project_id: str | None,
    ) -> dict[str, Any]:
        """Derive custody evidence only from immutable, re-readable execution rows."""
        project_id = self.resolve_project(project_id)
        if set(payload) != {"execution_id", "request_key"}:
            raise EvidenceError("invalid_derived_evidence_request", "Use exactly execution_id and request_key; manifests, classes, hashes, and scores are service-owned.")
        execution_id, request_key = payload.get("execution_id"), payload.get("request_key")
        if not isinstance(execution_id, str) or not execution_id or not isinstance(request_key, str) or not request_key:
            raise EvidenceError("invalid_derived_evidence_request", "execution_id and request_key must be non-empty strings.")
        binding, attempts, prices = self.repository.derived_execution_evidence_source(project_id, execution_id)
        if binding is None:
            raise EvidenceError("execution_not_found", "The execution was not found in this project.", status_code=404)
        manifest, receipt_kind = self._derive_manifest(project_id, binding, attempts, prices)
        receipt_id = sha256({"workflow": "derived-execution-receipt-v1", "project_id": project_id, "request_key": request_key})
        receipt = create_receipt(manifest, receipt_id=receipt_id)
        registered = self._registered_artifacts(manifest.artifact_hashes)
        verification = verify_evidence(
            receipt, manifest, self.artifact_store,
            evidence_type="fixture" if receipt_kind == _DERIVED_FIXTURE_KIND else "local_live",
            verifier_id="derived-execution-evidence-v1",
            verifier_digest=sha256({"service": "derived-execution-evidence-v1"}),
            registered_artifacts=registered,
        )
        if not verification.verified:
            raise EvidenceError("derived_evidence_hold", "Derived execution evidence cannot be freshly verified: " + "; ".join(verification.errors), status_code=409)
        try:
            replay = self.repository.create_evidence_receipt(
                project_id,
                receipt_id=receipt.receipt_id,
                receipt_hash=receipt.receipt_hash,
                manifest_hash=receipt.manifest_hash,
                manifest_json=manifest.model_dump(mode="json"),
                artifact_hashes=receipt.artifact_hashes,
                evidence_type=receipt_kind,
                claim_ceiling=manifest.claim_ceiling,
                execution_id=execution_id,
            )
        except ImmutableReceiptConflict as exc:
            raise EvidenceError("derived_receipt_conflict", "This request key is already bound to different immutable execution evidence.", status_code=409) from exc
        except ValueError as exc:
            raise EvidenceError("derived_evidence_hold", "Derived execution evidence cannot be persisted.", status_code=409) from exc
        return {**self.get_receipt(receipt.receipt_id, project_id=project_id), "admission_workflow": "derived_execution", "idempotent_replay": replay}

    def _derive_manifest(
        self, project_id: str, binding: Mapping[str, Any], attempt_rows: list[Mapping[str, Any]], price_rows: list[Mapping[str, Any]],
    ) -> tuple[EvidenceManifest, str]:
        holds: list[str] = []
        if binding.get("execution_status") != "completed":
            holds.append("execution is not completed")
        if binding.get("frozen_at") is None or not isinstance(binding.get("definition"), Mapping) or not binding.get("spec_hash") or not binding.get("study_pack_hash"):
            holds.append("execution does not bind a frozen experiment definition")
        if not attempt_rows:
            holds.append("execution has no attempts")

        records: list[dict[str, Any]] = []
        seen_fixture = False
        seen_live = False
        limitations: set[str] = set()
        exclusions: set[str] = set()
        artifact_hashes: set[str] = set()
        for row in attempt_rows:
            attempt_id = str(row["attempt_id"])
            request = row.get("request_metadata")
            result = row.get("result_metadata")
            jobs = row.get("jobs")
            evaluations = row.get("evaluations")
            if not isinstance(request, Mapping) or not isinstance(result, Mapping):
                holds.append(f"attempt {attempt_id} has malformed persisted metadata")
                continue
            if not isinstance(jobs, list):
                holds.append(f"attempt {attempt_id} has malformed persisted job bindings")
                continue
            attempt_jobs = [job for job in jobs if isinstance(job, Mapping) and job.get("kind") == "attempt"]
            evaluation_jobs = [job for job in jobs if isinstance(job, Mapping) and job.get("kind") == "evaluation"]
            unknown_jobs = [job for job in jobs if not isinstance(job, Mapping) or job.get("kind") not in {"attempt", "evaluation"}]
            if len(attempt_jobs) != 1 or len(evaluation_jobs) != 1 or unknown_jobs:
                holds.append(f"attempt {attempt_id} must have exactly one attempt and one evaluation job")
                continue
            attempt_job, evaluation_job = attempt_jobs[0], evaluation_jobs[0]
            if any(
                str(job.get("attempt_id")) != attempt_id
                or str(job.get("execution_id")) != str(binding["execution_id"])
                or job.get("status") != "completed"
                for job in (attempt_job, evaluation_job)
            ):
                holds.append(f"attempt {attempt_id} job binding or terminal state is inconsistent")
                continue
            payload = attempt_job.get("payload")
            harness_data = payload.get("harness") if isinstance(payload, Mapping) else None
            attempt_input_data = payload.get("attempt_input") if isinstance(payload, Mapping) else None
            envelope_data = request.get("envelope")
            terminal_data = result.get("terminal_envelope")
            try:
                harness = HarnessSpec.model_validate_json(canonical_json(harness_data))
                envelope = AttemptEnvelope.model_validate_json(canonical_json(envelope_data))
                terminal = AttemptEnvelope.model_validate_json(canonical_json(terminal_data))
                attempt_input = AttemptInput.model_validate_json(canonical_json(attempt_input_data))
            except (TypeError, ValueError, ValidationError):
                holds.append(f"attempt {attempt_id} lacks a valid persisted harness, input binding, or terminal envelope")
                continue
            if terminal.attempt_id != attempt_id or terminal.status not in {"completed", "failed", "timed_out", "cancelled", "incomplete"}:
                holds.append(f"attempt {attempt_id} terminal envelope is not captured")
            self._require_terminal_continuity(
                attempt_id, row, attempt_input, envelope, terminal, holds,
            )
            if not isinstance(evaluations, list) or len(evaluations) != 1:
                holds.append(f"attempt {attempt_id} must have exactly one immutable evaluation")
                continue
            evaluation = evaluations[0]
            evaluation_artifacts = self._evaluation_artifacts(evaluation, attempt_id, holds)
            execution_artifacts = self._attempt_artifacts(result, terminal, attempt_id, holds)
            if any(
                evaluation.get(field) != result.get(field)
                for field in ("input_artifact_digest", "output_artifact_digest", "trace_artifact_digest")
            ):
                holds.append(f"attempt {attempt_id} evaluation artifacts are not bound to persisted execution evidence")
            artifact_hashes.update(execution_artifacts)
            artifact_hashes.update(evaluation_artifacts)
            for item in result.get("limitations", ()) if isinstance(result.get("limitations", ()), list) else ():
                if isinstance(item, str):
                    limitations.add(item)
            if evaluation.get("exclusion_state") not in {None, "included"}:
                exclusions.add(f"attempt:{attempt_id}:{evaluation['exclusion_state']}")
            is_fixture = harness.claim_eligibility == "fixture_only"
            seen_fixture = seen_fixture or is_fixture
            seen_live = seen_live or not is_fixture
            usage_rows = row.get("usage_rows") if isinstance(row.get("usage_rows"), list) else []
            if not is_fixture:
                self._live_attempt_gates(attempt_id, harness, envelope, terminal, result, usage_rows, holds, limitations)
            records.append({
                "attempt_id": attempt_id,
                "harness": harness.model_dump(mode="json"),
                "request_envelope": envelope.model_dump(mode="json"),
                "terminal_envelope": terminal.model_dump(mode="json"),
                "evaluation": self._immutable_evaluation(evaluation),
                "usage": [self._immutable_usage(item) for item in usage_rows],
            })
        if seen_fixture and seen_live:
            holds.append("execution mixes fixture-only and live harness attempts")
        if holds:
            raise EvidenceError("derived_evidence_hold", "Derived execution receipt is HOLD: " + "; ".join(sorted(set(holds))), status_code=409)
        if not artifact_hashes:
            raise EvidenceError("derived_evidence_hold", "Derived execution receipt is HOLD: no execution or evaluation artifacts were persisted.", status_code=409)
        if any(not _is_digest(digest) for digest in artifact_hashes):
            raise EvidenceError("derived_evidence_hold", "Derived execution receipt is HOLD: persisted artifact evidence contains an invalid digest.", status_code=409)
        registered = self._registered_artifacts(tuple(sorted(artifact_hashes)))
        if set(registered) != artifact_hashes:
            raise EvidenceError("derived_evidence_hold", "Derived execution receipt is HOLD: an execution or evaluation artifact is not registered.", status_code=409)
        price_evidence = self._price_evidence(records, price_rows)
        if seen_live and not price_evidence:
            limitations.add("central_price_evidence_missing")
        evidence_class = EvidenceClass.LOCAL_LIVE if seen_live else EvidenceClass.FIXTURE
        ceiling = _ADMISSION_CEILINGS[evidence_class]
        aggregates = self._aggregate_identities(records, price_evidence)
        manifest = EvidenceManifest(
            experiment_id=str(binding["experiment_id"]),
            experiment_hash=sha256(binding["definition"]),
            study_pack_hash=str(binding["study_pack_hash"]),
            spec_hash=str(binding["spec_hash"]),
            code_hash=aggregates["code_hash"], runtime_hash=aggregates["runtime_hash"],
            adapter_hash=aggregates["adapter_hash"], model_hash=aggregates["model_hash"],
            price_hash=aggregates["price_hash"], evaluator_hashes=(aggregates["evaluator_hash"],),
            artifact_hashes=tuple(sorted(artifact_hashes)), exclusions=tuple(sorted(exclusions)),
            limitations=tuple(sorted(limitations)), evidence_class=evidence_class,
            claim_ceiling=ceiling,
        )
        return manifest, _DERIVED_LOCAL_LIVE_KIND if seen_live else _DERIVED_FIXTURE_KIND

    @staticmethod
    def _attempt_artifacts(result: Mapping[str, Any], terminal: AttemptEnvelope, attempt_id: str, holds: list[str]) -> set[str]:
        artifacts = {str(value) for key, value in result.items() if key in _DIGEST_KEYS and isinstance(value, str)}
        for value in result.get("artifact_digests", ()) if isinstance(result.get("artifact_digests", ()), list) else ():
            if isinstance(value, str):
                artifacts.add(value)
        if not isinstance(result.get("input_artifact_digest"), str) or not isinstance(result.get("trace_artifact_digest"), str):
            holds.append(f"attempt {attempt_id} lacks input or trace artifact evidence")
        if terminal.status == "completed" and not isinstance(result.get("output_artifact_digest"), str):
            holds.append(f"completed attempt {attempt_id} lacks output artifact evidence")
        if terminal.status == "completed" and terminal.response_hash != result.get("output_artifact_digest"):
            holds.append(f"completed attempt {attempt_id} output artifact does not bind the terminal response")
        return artifacts

    def _evaluation_artifacts(self, evaluation: Mapping[str, Any], attempt_id: str, holds: list[str]) -> set[str]:
        required = ("evaluator_digest", "result_hash", "result_artifact_digest", "input_artifact_digest", "output_artifact_digest", "trace_artifact_digest")
        if any(not _is_digest(evaluation.get(key)) for key in required):
            holds.append(f"attempt {attempt_id} evaluation lacks immutable evaluator, result, or artifact binding")
            return set()
        result_artifact = str(evaluation["result_artifact_digest"])
        try:
            if sha256_bytes(self.artifact_store.get_bytes(result_artifact)) != evaluation["result_hash"]:
                holds.append(f"attempt {attempt_id} evaluator result artifact does not match its result hash")
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            holds.append(f"attempt {attempt_id} evaluator result artifact is unreadable")
        return {str(evaluation[key]) for key in ("result_artifact_digest", "input_artifact_digest", "output_artifact_digest", "trace_artifact_digest")}

    @staticmethod
    def _require_terminal_continuity(
        attempt_id: str, row: Mapping[str, Any], attempt_input: AttemptInput,
        request: AttemptEnvelope, terminal: AttemptEnvelope, holds: list[str],
    ) -> None:
        if attempt_input.attempt != request or attempt_input.scenario.scenario_id != row.get("scenario_id"):
            holds.append(f"attempt {attempt_id} persisted request input is not bound to its attempt or scenario")
        if request.attempt_id != attempt_id or request.episode_id != terminal.episode_id or request.ordinal != terminal.ordinal or request.ordinal != int(row["attempt_ordinal"]) + 1:
            holds.append(f"attempt {attempt_id} request or terminal attempt identity is inconsistent")
        for field in (
            "provider", "provider_model", "endpoint_id", "pinned_endpoint_digest", "harness_id",
            "factor_assignments", "budget", "provenance", "request_hash", "queued_at",
        ):
            if getattr(request, field) != getattr(terminal, field):
                holds.append(f"attempt {attempt_id} terminal envelope changes immutable request field {field}")

    @staticmethod
    def _live_attempt_gates(attempt_id: str, harness: HarnessSpec, envelope: AttemptEnvelope, terminal: AttemptEnvelope, result: Mapping[str, Any], usage_rows: list[Mapping[str, Any]], holds: list[str], limitations: set[str]) -> None:
        if harness.claim_eligibility not in {"live_provider", "externally_validated"} or harness.adapter == "recorded":
            holds.append(f"attempt {attempt_id} does not bind a non-fixture live harness")
        if not envelope.pinned_endpoint_digest or not terminal.observed_endpoint_digest or not terminal.observed_provider_version or terminal.observed_endpoint_digest != envelope.pinned_endpoint_digest:
            holds.append(f"attempt {attempt_id} lacks pinned and observed provider endpoint identity")
        if not isinstance(result.get("usage"), Mapping):
            limitations.add(f"attempt:{attempt_id}:provider_usage_missing")
            holds.append(f"attempt {attempt_id} lacks provider-reported usage")
        if (harness.capabilities.tools or harness.capabilities.state) and (harness.execution_mode not in {"container", "remote"} or harness.isolation not in {"container", "remote_sandbox"}):
            holds.append(f"attempt {attempt_id} lacks OCI or remote-sandbox isolation for tool/state use")
        if not usage_rows:
            limitations.add(f"attempt:{attempt_id}:central_cost_record_missing")

    @staticmethod
    def _immutable_evaluation(row: Mapping[str, Any]) -> dict[str, Any]:
        return {key: row.get(key) for key in ("id", "evaluator", "evaluator_version", "evaluator_digest", "result_hash", "result_artifact_digest", "input_artifact_digest", "output_artifact_digest", "trace_artifact_digest", "result", "exclusion_state")}

    @staticmethod
    def _immutable_usage(row: Mapping[str, Any]) -> dict[str, Any]:
        return {key: row.get(key) for key in ("id", "model_id", "input_tokens", "output_tokens", "total_tokens", "context_tokens", "tool_calls", "cost_status", "cost_usd", "actual_cost_usd", "price_catalog_revision", "provider_usage_digest")}

    @staticmethod
    def _price_evidence(records: list[dict[str, Any]], price_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        wanted = {(item["model_id"], item["price_catalog_revision"]) for record in records for item in record["usage"] if item.get("price_catalog_revision")}
        return [dict(row) for row in price_rows if (row.get("model_id"), row.get("revision")) in wanted]

    @staticmethod
    def _aggregate_identities(records: list[dict[str, Any]], price_evidence: list[dict[str, Any]]) -> dict[str, str]:
        ordered = sorted(records, key=lambda item: item["attempt_id"])
        return {
            "code_hash": sha256({"aggregate": "persisted-harness-code-v1", "attempts": [{"adapter_digest": item["harness"]["adapter_digest"], "effective_configuration_hash": item["harness"]["effective_configuration_hash"]} for item in ordered]}),
            "runtime_hash": sha256({"aggregate": "persisted-runtime-v1", "attempts": [item["request_envelope"]["provenance"] for item in ordered]}),
            "adapter_hash": sha256({"aggregate": "persisted-adapter-v1", "attempts": [{"adapter": item["harness"]["adapter"], "adapter_identity": item["harness"]["adapter_identity"], "adapter_digest": item["harness"]["adapter_digest"]} for item in ordered]}),
            "model_hash": sha256({"aggregate": "persisted-model-v1", "attempts": [{"provider": item["request_envelope"]["provider"], "provider_model": item["request_envelope"]["provider_model"], "observed_provider_version": item["terminal_envelope"]["observed_provider_version"], "observed_endpoint_digest": item["terminal_envelope"]["observed_endpoint_digest"]} for item in ordered]}),
            "price_hash": sha256({"aggregate": "persisted-price-v1", "usage": [item for record in ordered for item in record["usage"]], "catalog": sorted(price_evidence, key=lambda item: str(item.get("id")))}),
            "evaluator_hash": sha256({"aggregate": "persisted-evaluator-v1", "evaluations": [item["evaluation"] for item in ordered]}),
        }

    def get_receipt(self, receipt_id: str, *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        row = self.repository.get_evidence_receipt(project_id, receipt_id)
        if row is None or not self._is_durable_receipt(row):
            raise EvidenceError("evidence_not_found", "The requested evidence receipt was not found.", status_code=404)
        manifest = self._manifest(row)
        result = {
            "receipt_id": row["id"],
            "receipt_hash": row["receipt_hash"],
            "manifest_hash": row["manifest_hash"],
            "evidence_type": row["receipt_kind"],
            "evidence_class": manifest.evidence_class.value,
            "claim_ceiling": row["claim_ceiling"],
            "integrity_not_truth": True,
            "artifacts": [
                {"sha256": digest, "disposition": "withheld", "reason": _REDACTION}
                for digest in tuple(row["artifact_hashes"] or ())
            ],
        }
        if row["receipt_kind"] in {_DERIVED_FIXTURE_KIND, _DERIVED_LOCAL_LIVE_KIND}:
            result["admission_workflow"] = "derived_execution"
        return result

    def list_receipts(
        self,
        *,
        project_id: str | None,
        execution_id: str | None = None,
        kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return freshly verified, project-scoped receipt summaries only."""
        project_id = self.resolve_project(project_id)
        limit, offset = self._page(limit, offset)
        statement = select(evidence_receipts).where(
            evidence_receipts.c.project_id == project_id
        )
        if execution_id is not None:
            statement = statement.where(evidence_receipts.c.execution_id == execution_id)
        if kind is not None:
            statement = statement.where(evidence_receipts.c.receipt_kind == kind)
        with self.repository.engine.connect() as conn:
            rows = conn.execute(
                statement.order_by(evidence_receipts.c.created_at, evidence_receipts.c.id)
            ).mappings().all()
        summaries = [self._list_summary(project_id, row) for row in rows if self._is_durable_receipt(row)]
        page = summaries[offset : offset + limit]
        return {
            "evidence": page,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "next_offset": offset + limit if len(summaries) > offset + limit else None,
            },
            "integrity_not_truth": True,
            "claim_ceiling": "receipt-specific; summaries expose custody metadata only",
        }

    def verify_receipt(self, receipt_id: str, *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        row = self.repository.get_evidence_receipt(project_id, receipt_id)
        if row is None or not self._is_durable_receipt(row):
            raise EvidenceError("evidence_not_found", "The requested evidence receipt was not found.", status_code=404)
        verification = self._verify_stored_receipt(project_id, row)
        return {
            "receipt_id": receipt_id,
            "verified": verification.verified,
            "errors": list(verification.errors),
            "receipt_hash": verification.receipt_hash,
            "manifest_hash": verification.manifest_hash,
            "integrity_not_truth": True,
            "claim_ceiling": row["claim_ceiling"],
        }

    def create_reproduction(self, payload: Mapping[str, Any], *, project_id: str | None) -> dict[str, Any]:
        project_id = self.resolve_project(project_id)
        expected = {
            "receipt", "original_evidence_receipt_id", "reproduced_evidence_receipt_id", "external_attestation",
        }
        if set(payload) != expected:
            raise EvidenceError("invalid_reproduction", "Use exactly receipt, original_evidence_receipt_id, reproduced_evidence_receipt_id, and external_attestation.")
        original_id, reproduced_id = payload.get("original_evidence_receipt_id"), payload.get("reproduced_evidence_receipt_id")
        if not isinstance(original_id, str) or not isinstance(reproduced_id, str) or original_id == reproduced_id:
            raise EvidenceError("invalid_reproduction", "Two distinct evidence receipt identifiers are required.")
        original = self.repository.get_evidence_receipt(project_id, original_id)
        reproduced = self.repository.get_evidence_receipt(project_id, reproduced_id)
        if original is None or reproduced is None or not self._is_durable_receipt(original) or not self._is_durable_receipt(reproduced):
            raise EvidenceError("evidence_not_found", "The requested evidence receipt was not found.", status_code=404)
        if not self._verify_stored_receipt(project_id, original).verified or not self._verify_stored_receipt(project_id, reproduced).verified:
            raise EvidenceError(
                "reproduction_source_unverified",
                "Both stored source receipts must pass fresh integrity verification.",
                status_code=409,
            )
        try:
            receipt = ReproductionReceipt.model_validate_json(canonical_json(payload["receipt"]))
        except (TypeError, ValidationError) as exc:
            raise EvidenceError("invalid_reproduction", "The reproduction receipt is malformed or self-asserts independence.") from exc
        if receipt.original_manifest_hash != original["manifest_hash"] or receipt.reproduced_manifest_hash != reproduced["manifest_hash"]:
            raise EvidenceError("reproduction_mismatch", "The reproduction receipt is not bound to the supplied evidence manifests.", status_code=409)
        reproduction_hash = sha256(receipt.model_dump(mode="json"))
        attestation = self._attestation(payload["external_attestation"], receipt, reproduction_hash)
        claim_ceiling = "reproduction custody/integrity only; no correctness or independent-reproduction claim"
        try:
            replay = self.repository.create_reproduction(
                project_id,
                reproduction_id=receipt.receipt_id,
                reproduction_hash=reproduction_hash,
                original_receipt_id=original_id,
                reproduced_receipt_id=reproduced_id,
                receipt_json=receipt.model_dump(mode="json"),
                external_attestation=attestation.model_dump(mode="json") if attestation else None,
                claim_ceiling=claim_ceiling,
            )
        except ImmutableReceiptConflict as exc:
            raise EvidenceError("reproduction_conflict", "The reproduction identifier is already bound to different evidence.", status_code=409) from exc
        except ValueError as exc:
            raise EvidenceError("reproduction_rejected", "The reproduction evidence cannot be stored in this project.", status_code=409) from exc
        return {
            "reproduction_receipt_id": receipt.receipt_id,
            "reproduction_hash": reproduction_hash,
            "original_evidence_receipt_id": original_id,
            "reproduced_evidence_receipt_id": reproduced_id,
            "external_attestation_contract": "recorded" if attestation else "missing",
            "independently_verified": False,
            "claim_ceiling": claim_ceiling,
            "integrity_not_truth": True,
            "idempotent_replay": replay,
        }

    def _registered_artifacts(self, digests: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        with self.repository.engine.connect() as conn:
            rows = conn.execute(select(artifacts).where(artifacts.c.digest.in_(digests))).mappings().all()
        return {str(row["digest"]): dict(row) for row in rows}

    def _list_summary(self, project_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
        """Fail closed before presenting stored metadata as durable custody evidence."""
        manifest = self._manifest(row)
        if row["execution_id"] is not None:
            self._require_execution_binding(project_id, str(row["execution_id"]), manifest)
        verification = self._verify_stored_receipt(project_id, row)
        if not verification.verified:
            raise EvidenceError(
                "evidence_integrity_hold",
                "A stored evidence receipt cannot be verified for truthful summary recovery.",
                status_code=409,
            )
        result = {
            "receipt_id": row["id"],
            "created_at": row["created_at"],
            "execution_id": row["execution_id"],
            "receipt_hash": row["receipt_hash"],
            "manifest_hash": row["manifest_hash"],
            "evidence_type": row["receipt_kind"],
            "evidence_class": manifest.evidence_class.value,
            "artifact_count": len(tuple(row["artifact_hashes"] or ())),
            "artifact_content": "withheld",
            "claim_ceiling": row["claim_ceiling"],
            "integrity_not_truth": True,
        }
        if row["receipt_kind"] in {_DERIVED_FIXTURE_KIND, _DERIVED_LOCAL_LIVE_KIND}:
            result["admission_workflow"] = "derived_execution"
        return result

    def _require_execution_binding(
        self, project_id: str, execution_id: str, manifest: EvidenceManifest,
    ) -> None:
        binding = self.repository.get_execution_evidence_binding(project_id, execution_id)
        if (
            binding is None
            or binding["execution_status"] == "legacy_local_unverified"
            or binding["frozen_at"] is None
            or binding["spec_hash"] is None
            or binding["study_pack_hash"] is None
            or not isinstance(binding["definition"], Mapping)
            or manifest.experiment_id != binding["experiment_id"]
            or manifest.experiment_hash != sha256(binding["definition"])
            or manifest.spec_hash != binding["spec_hash"]
            or manifest.study_pack_hash != binding["study_pack_hash"]
        ):
            raise EvidenceError(
                "execution_binding_mismatch",
                "The supplied execution cannot be bound to this evidence manifest.",
                status_code=409,
            )

    @staticmethod
    def _is_durable_receipt(row: Mapping[str, Any]) -> bool:
        return all(row.get(field) is not None for field in ("project_id", "receipt_hash", "manifest_hash", "manifest_json", "artifact_hashes", "claim_ceiling")) and row.get("integrity_not_truth") is True

    @staticmethod
    def _page(limit: int, offset: int) -> tuple[int, int]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise EvidenceError("invalid_limit", "The list limit must be an integer from 1 to 100.")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise EvidenceError("invalid_offset", "The list offset must be a nonnegative integer.")
        return limit, offset

    @staticmethod
    def _verification_evidence_type(receipt_kind: str) -> str:
        if receipt_kind == _DERIVED_FIXTURE_KIND:
            return "fixture"
        if receipt_kind == _DERIVED_LOCAL_LIVE_KIND:
            return "local_live"
        return receipt_kind

    @staticmethod
    def _manifest(row: Mapping[str, Any]) -> EvidenceManifest:
        try:
            manifest = EvidenceManifest.model_validate_json(canonical_json(row["manifest_json"]))
        except ValidationError as exc:
            raise EvidenceError("receipt_storage_invalid", "The stored manifest metadata is invalid.", status_code=409) from exc
        if sha256(manifest) != row["manifest_hash"]:
            raise EvidenceError("receipt_storage_invalid", "The stored manifest hash is inconsistent.", status_code=409)
        return manifest

    def _verify_stored_receipt(self, project_id: str, row: Mapping[str, Any]):
        manifest = self._manifest(row)
        try:
            receipt = EvidenceReceipt(
                receipt_id=str(row["id"]), manifest_hash=str(row["manifest_hash"]),
                artifact_hashes=tuple(row["artifact_hashes"] or ()), receipt_hash=str(row["receipt_hash"]),
            )
        except ValidationError as exc:
            raise EvidenceError("receipt_storage_invalid", "The stored receipt metadata is invalid.", status_code=409) from exc
        return verify_evidence(
            receipt,
            manifest,
            self.artifact_store,
            evidence_type=self._verification_evidence_type(str(row["receipt_kind"])),
            verifier_id="evidence-verifier-v1",
            verifier_digest=sha256({"service": "evidence-verifier-v1"}),
            registered_artifacts=self.repository.evidence_artifacts(project_id, str(row["id"])),
        )

    @staticmethod
    def _attestation(
        value: Any, receipt: ReproductionReceipt, reproduction_hash: str,
    ) -> ExternalIndependenceAttestation | None:
        if value is None:
            return None
        try:
            attestation = ExternalIndependenceAttestation.model_validate_json(canonical_json(value))
        except (TypeError, ValidationError) as exc:
            raise EvidenceError("invalid_independence_attestation", "External attestation must satisfy the distinct-authority contract.") from exc
        if attestation.reproduction_receipt_hash != reproduction_hash or (
            attestation.original_operator_id != receipt.original_operator_id
            or attestation.original_authority_id != receipt.original_authority_id
            or attestation.reproducer_operator_id != receipt.reproducer_operator_id
            or attestation.reproducer_authority_id != receipt.reproducer_authority_id
        ):
            raise EvidenceError("invalid_independence_attestation", "External attestation is not bound to this reproduction receipt.", status_code=409)
        return attestation
