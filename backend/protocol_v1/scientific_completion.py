"""Offline-only contracts for preregistered Protocol-v1 matrix studies.

This module deliberately creates dispatch plans and recorded-fixture bundles,
never provider requests.  Live execution remains owned by the existing
controller/worker/evidence chain after a public immutable preregistration.
"""

from __future__ import annotations

from datetime import datetime
from itertools import product
from pathlib import Path, PurePosixPath
from stat import S_ISREG
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canonical import canonical_json, sha256, sha256_bytes

_DIGEST = r"^[a-f0-9]{64}$"
_RUNTIME_KINDS = frozenset({"ollama", "lm_studio"})
_LOCAL_COST_POLICY = "zero_paid_cost_local_energy_unknown"


class ScientificModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PreregistrationStatus(ScientificModel):
    artifact_uri: str = Field(min_length=1)
    artifact_hash: str = Field(pattern=_DIGEST)
    publication_state: Literal["hold_not_public", "public_immutable"]
    publication_id: str | None = None
    published_at: datetime | None = None

    @model_validator(mode="after")
    def publication_fields_are_truthful(self) -> PreregistrationStatus:
        public = self.publication_state == "public_immutable"
        if public != (self.publication_id is not None and self.published_at is not None):
            raise ValueError("public immutable preregistration requires exactly publication id and timestamp")
        if self.published_at is not None and (self.published_at.tzinfo is None or self.published_at.utcoffset() is None):
            raise ValueError("published_at must be timezone-aware")
        return self


class FrozenIdentifier(ScientificModel):
    id: str = Field(min_length=1)
    digest: str = Field(pattern=_DIGEST)


class FrozenRuntime(ScientificModel):
    id: str = Field(min_length=1)
    kind: Literal["ollama", "lm_studio"]
    identity_digest: str = Field(pattern=_DIGEST)
    paid_cost_policy: Literal["zero_paid_cost_local_energy_unknown"]


class FrozenBindings(ScientificModel):
    models: tuple[FrozenIdentifier, ...] = Field(min_length=1)
    harnesses: tuple[FrozenIdentifier, ...] = Field(min_length=1)
    runtimes: tuple[FrozenRuntime, ...] = Field(min_length=1)
    evaluators: tuple[FrozenIdentifier, ...] = Field(min_length=1)
    sampling_digest: str = Field(pattern=_DIGEST)
    budget_digest: str = Field(pattern=_DIGEST)
    stopping_digest: str = Field(pattern=_DIGEST)
    exclusions_digest: str = Field(pattern=_DIGEST)
    severe_failure_digest: str = Field(pattern=_DIGEST)
    analysis_digest: str = Field(pattern=_DIGEST)
    multiplicity_digest: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> FrozenBindings:
        for name in ("models", "harnesses", "runtimes", "evaluators"):
            values = getattr(self, name)
            if len({item.id for item in values}) != len(values):
                raise ValueError(f"frozen {name} must have unique ids")
        return self


class StudyCohort(ScientificModel):
    cohort_id: str = Field(min_length=1)
    role: Literal["flagship", "selection", "transfer"]
    task_ids: tuple[str, ...] = Field(min_length=1)
    domain_ids: tuple[str, ...] = Field(min_length=1)
    model_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def member_ids_are_unique(self) -> StudyCohort:
        for name in ("task_ids", "domain_ids", "model_ids"):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(f"cohort {name} must be unique")
        return self


class MatrixDeclaration(ScientificModel):
    models: tuple[str, ...] = Field(min_length=1)
    harnesses: tuple[str, ...] = Field(min_length=1)
    tasks: tuple[str, ...] = Field(min_length=1)
    domains: tuple[str, ...] = Field(min_length=1)
    cohorts: tuple[str, ...] = Field(min_length=1)
    repetitions: int = Field(ge=1, le=1000)

    @model_validator(mode="after")
    def matrix_axes_are_unique(self) -> MatrixDeclaration:
        for name in ("models", "harnesses", "tasks", "domains", "cohorts"):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(f"matrix {name} must be unique")
        return self

class RuntimeAdmission(ScientificModel):
    runtime_id: str = Field(min_length=1)
    kind: Literal["ollama", "lm_studio", "openai_compatible"]
    endpoint_identity_digest: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def reject_generic_adapter(self) -> RuntimeAdmission:
        if self.kind not in _RUNTIME_KINDS:
            raise ValueError("generic OpenAI-compatible adapter is not an admissible local runtime")
        return self


class FrozenSelectionReceipt(ScientificModel):
    receipt_hash: str = Field(pattern=_DIGEST)
    selection_configuration_hash: str = Field(pattern=_DIGEST)
    transfer_configuration_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def configurations_are_identical(self) -> FrozenSelectionReceipt:
        if self.selection_configuration_hash != self.transfer_configuration_hash:
            raise ValueError("selection and transfer frozen configurations must be equal")
        return self


class ScientificStudy(ScientificModel):
    study_id: str = Field(min_length=1)
    study_kind: Literal["flagship", "transfer"]
    claim_ceiling: str = Field(min_length=1)
    bundle_created_at: datetime
    preregistration: PreregistrationStatus
    frozen_bindings: FrozenBindings
    matrix: MatrixDeclaration
    cohorts: tuple[StudyCohort, ...] = Field(min_length=1)
    runtime_admissions: tuple[RuntimeAdmission, ...] = Field(min_length=1)
    frozen_selection_receipt: FrozenSelectionReceipt | None = None
    no_retuning: bool = False

    @model_validator(mode="after")
    def enforce_protocol_invariants(self) -> ScientificStudy:
        if self.bundle_created_at.tzinfo is None or self.bundle_created_at.utcoffset() is None:
            raise ValueError("bundle_created_at must be timezone-aware")
        cohort_ids = {item.cohort_id for item in self.cohorts}
        if len(cohort_ids) != len(self.cohorts) or set(self.matrix.cohorts) != cohort_ids:
            raise ValueError("matrix cohorts must exactly match declared cohorts")
        for matrix_axis, cohort_axis in (("models", "model_ids"), ("tasks", "task_ids"), ("domains", "domain_ids")):
            declared = set(getattr(self.matrix, matrix_axis))
            covered = {value for cohort in self.cohorts for value in getattr(cohort, cohort_axis)}
            if declared != covered:
                raise ValueError(f"matrix {matrix_axis} must exactly match the cohort assignments")
        if not set(self.matrix.models).issubset({item.id for item in self.frozen_bindings.models} | {model for cohort in self.cohorts for model in cohort.model_ids}):
            raise ValueError("matrix models must be frozen or explicitly cohort-bound")
        if not set(self.matrix.harnesses).issubset({item.id for item in self.frozen_bindings.harnesses}):
            raise ValueError("matrix harnesses must be frozen")
        runtimes = {item.id: item for item in self.frozen_bindings.runtimes}
        admissions = {item.runtime_id: item for item in self.runtime_admissions}
        if set(runtimes) != set(admissions) or any(runtimes[key].kind != value.kind or runtimes[key].identity_digest != value.endpoint_identity_digest for key, value in admissions.items()):
            raise ValueError("every admitted runtime must match a frozen explicit local runtime identity")
        if self.study_kind == "flagship":
            if any(item.role != "flagship" for item in self.cohorts) or self.frozen_selection_receipt is not None or self.no_retuning:
                raise ValueError("flagship studies cannot carry transfer-only selection controls")
        else:
            selection = [item for item in self.cohorts if item.role == "selection"]
            transfer = [item for item in self.cohorts if item.role == "transfer"]
            if len(selection) != 1 or len(transfer) != 1 or self.frozen_selection_receipt is None or not self.no_retuning:
                raise ValueError("transfer studies require one selection and transfer cohort, frozen receipt, and no_retuning")
            for axis in ("task_ids", "domain_ids", "model_ids"):
                if set(getattr(selection[0], axis)) & set(getattr(transfer[0], axis)):
                    raise ValueError(f"selection and transfer {axis} must be disjoint")
        return self

    @property
    def cell_count(self) -> int:
        """Return the expanded count after applying each cohort's axes."""
        return len(_cells(self))


class ConfirmatoryHold(RuntimeError):
    pass


class AttemptEvidence(ScientificModel):
    """Data-only result admission checks; runners must retain every terminal outcome."""

    cell_id: str = Field(min_length=1)
    evidence_class: Literal["fixture", "local_live"]
    terminal_status: Literal["completed", "failed", "timed_out", "cancelled", "incomplete"]
    provider_usage: tuple[tuple[str, int], ...] | None = None
    paid_cost_usd: float | None = Field(default=None, ge=0.0)
    energy_status: Literal["unknown"] = "unknown"
    severe_failures: tuple[str, ...]
    excluded: bool = False
    exclusion_reason: str | None = None

    @model_validator(mode="after")
    def validate_fixture_and_cost_boundary(self) -> AttemptEvidence:
        if self.excluded != (self.exclusion_reason is not None):
            raise ValueError("exclusions require a retained exclusion reason")
        if self.evidence_class == "fixture":
            if self.provider_usage is not None or self.paid_cost_usd is not None:
                raise ValueError("fixture evidence must not carry provider usage or paid cost")
        elif self.provider_usage is None:
            raise ValueError("local live evidence requires provider usage")
        elif self.paid_cost_usd != 0.0 or self.energy_status != "unknown":
            raise ValueError("local runtime evidence uses zero paid cost with local energy unknown")
        if len(set(self.severe_failures)) != len(self.severe_failures) or any(not value for value in self.severe_failures):
            raise ValueError("severe failures must be retained as unique non-empty labels")
        return self


def validate_evidence_matrix(study: ScientificStudy, evidence: tuple[AttemptEvidence, ...]) -> None:
    expected = {sha256(cell) for cell in _cells(study)}
    actual = [item.cell_id for item in evidence]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("evidence records must cover every matrix cell exactly once")


class BundleManifest(ScientificModel):
    bundle_hash: str = Field(pattern=_DIGEST)
    files: tuple[FrozenIdentifier, ...] = Field(min_length=1)
    reproduction_command: tuple[str, ...] = Field(min_length=1)
    signature: dict[str, str | None]
    created_at: datetime
    integrity_not_truth: Literal[True] = True

    @model_validator(mode="after")
    def validate_manifest_shape(self) -> BundleManifest:
        if self.signature != {"state": "HOLD_EXTERNAL_KEYLESS_SIGNATURE_REQUIRED", "bundle": None}:
            raise ValueError("bundle signature must truthfully hold for an external keyless signature")
        if "--mode" not in self.reproduction_command:
            raise ValueError("bundle manifest requires an exact reproduction command")
        return self


def canonical_study_hash(study: ScientificStudy) -> str:
    return sha256(study.model_dump(mode="json"))


def _is_placeholder_digest(value: str) -> bool:
    """Reject obvious fixture sentinels from confirmatory admission only."""
    return any(
        value == value[:period] * (len(value) // period)
        for period in (1, 2, 4)
    )


def _placeholder_binding_references(study: ScientificStudy) -> tuple[str, ...]:
    bindings = study.frozen_bindings
    candidates = [
        ("preregistration.artifact_hash", study.preregistration.artifact_hash),
        *(
            (f"models[{item.id}].digest", item.digest)
            for item in bindings.models
        ),
        *(
            (f"harnesses[{item.id}].digest", item.digest)
            for item in bindings.harnesses
        ),
        *(
            (f"runtimes[{item.id}].identity_digest", item.identity_digest)
            for item in bindings.runtimes
        ),
        *(
            (f"evaluators[{item.id}].digest", item.digest)
            for item in bindings.evaluators
        ),
        ("sampling_digest", bindings.sampling_digest),
        ("budget_digest", bindings.budget_digest),
        ("stopping_digest", bindings.stopping_digest),
        ("exclusions_digest", bindings.exclusions_digest),
        ("severe_failure_digest", bindings.severe_failure_digest),
        ("analysis_digest", bindings.analysis_digest),
        ("multiplicity_digest", bindings.multiplicity_digest),
    ]
    if study.frozen_selection_receipt is not None:
        selection = study.frozen_selection_receipt
        candidates.extend(
            (
                ("frozen_selection_receipt.receipt_hash", selection.receipt_hash),
                (
                    "frozen_selection_receipt.selection_configuration_hash",
                    selection.selection_configuration_hash,
                ),
                (
                    "frozen_selection_receipt.transfer_configuration_hash",
                    selection.transfer_configuration_hash,
                ),
            )
        )
    return tuple(name for name, digest in candidates if _is_placeholder_digest(digest))


def resolve_study_artifact(study_root: str | Path, relative_uri: str) -> Path:
    """Resolve a declared artifact only if it is an in-root regular file."""
    root = Path(study_root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("study root must be a real directory")
    root = root.resolve(strict=True)
    if not relative_uri or "\\" in relative_uri:
        raise ValueError("artifact URI must be a non-empty normalized relative POSIX path")
    relative = PurePosixPath(relative_uri)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("artifact URI must stay beneath the study root")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("study artifact path must not traverse a symlink")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
        mode = resolved.stat().st_mode
    except (OSError, ValueError) as exc:
        raise ValueError("study artifact must be an existing in-root regular file") from exc
    if not S_ISREG(mode):
        raise ValueError("study artifact must be a regular file")
    return resolved


def _cells(study: ScientificStudy) -> list[dict[str, str | int]]:
    cohorts = {item.cohort_id: item for item in study.cohorts}
    return [
        {"model_id": model, "harness_id": harness, "task_id": task, "domain_id": domain, "cohort_id": cohort_id, "repeat_index": repeat}
        for cohort_id in study.matrix.cohorts
        for model, harness, task, domain, repeat in product(
            cohorts[cohort_id].model_ids,
            study.matrix.harnesses,
            cohorts[cohort_id].task_ids,
            cohorts[cohort_id].domain_ids,
            range(1, study.matrix.repetitions + 1),
        )
    ]


def build_fixture_bundle(study: ScientificStudy, *, mode: Literal["fixture", "confirmatory"] = "fixture") -> dict[str, object]:
    if mode == "confirmatory" and study.preregistration.publication_state != "public_immutable":
        raise ConfirmatoryHold(
            "HOLD_PREREGISTRATION_NOT_PUBLIC_IMMUTABLE: confirmatory dispatch requires a public immutable preregistration"
        )
    placeholders = _placeholder_binding_references(study)
    if mode == "confirmatory" and placeholders:
        raise ConfirmatoryHold(
            "HOLD_PLACEHOLDER_FROZEN_BINDINGS: confirmatory dispatch rejects placeholder/sentinel bindings: "
            + ", ".join(placeholders)
        )
    status = "ADMISSION_READY_NOT_EXECUTED" if mode == "confirmatory" else "HOLD_PREREGISTRATION_NOT_PUBLIC_IMMUTABLE"
    cell_records = _cells(study)
    for record in cell_records:
        record["cell_id"] = sha256(record)
    return {
        "protocol_version": "scientific-completion-v1",
        "study_id": study.study_id,
        "study_hash": canonical_study_hash(study),
        "mode": mode,
        "claim_ceiling": study.claim_ceiling,
        "confirmatory_status": status,
        "execution_path": "execution_v1.controller -> execution_v1.worker -> services_v1.evidence",
        "fixture_live_separation": {"fixture_only": mode == "fixture", "provider_requests_started": False},
        "cost_policy": _LOCAL_COST_POLICY,
        "matrix": {"expected_cells": len(cell_records), "cells": cell_records},
        "analysis_groups": ["model", "harness", "task_domain", "cohort", "transfer_status"],
        "retention": {"severe_failures": "required", "uncertainty": "required", "exclusions": "required"},
    }


def write_fixture_bundle(study: ScientificStudy, output_root: str | Path, *, mode: Literal["fixture", "confirmatory"] = "fixture") -> Path:
    root = Path(output_root)
    target = root / f"{study.study_id}-{canonical_study_hash(study)[:16]}"
    if target.exists():
        raise FileExistsError(f"collision-gated output already exists: {target}")
    target.mkdir(parents=True)
    bundle = build_fixture_bundle(study, mode=mode)
    bundle_path = target / "fixture-bundle.json"
    bundle_path.write_bytes(canonical_json(bundle))
    analysis_template = {
        "study_id": study.study_id,
        "study_hash": canonical_study_hash(study),
        "group_by": ["model", "harness", "task_domain", "cohort", "transfer_status"],
        "required_fields": ["attempt_count", "success", "severe_failures", "exclusions", "uncertainty"],
        "status": "FIXTURE_TEMPLATE_NOT_EMPIRICAL_RESULT",
    }
    analysis_path = target / "analysis-report-template.json"
    analysis_path.write_bytes(canonical_json(analysis_template))
    manifest = BundleManifest(
        bundle_hash=sha256_bytes(bundle_path.read_bytes()),
        files=(
            FrozenIdentifier(id=bundle_path.name, digest=sha256_bytes(bundle_path.read_bytes())),
            FrozenIdentifier(id=analysis_path.name, digest=sha256_bytes(analysis_path.read_bytes())),
        ),
        reproduction_command=("uv", "run", "--project", "backend", "python", "scripts/run-protocol-v1-matrix.py", "--study", study.study_id, "--mode", mode),
        signature={"state": "HOLD_EXTERNAL_KEYLESS_SIGNATURE_REQUIRED", "bundle": None},
        created_at=study.bundle_created_at,
    )
    (target / "bundle-manifest.json").write_bytes(canonical_json(manifest.model_dump(mode="json")))
    return target


def load_scientific_study(path: str | Path) -> ScientificStudy:
    return ScientificStudy.model_validate_json(Path(path).read_text(encoding="utf-8"))
