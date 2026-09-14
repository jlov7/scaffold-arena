from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from protocol_v1.canonical import sha256, sha256_bytes

from .models import (
    EvidenceManifest,
    EvidenceReceipt,
    EvidenceVerification,
    ReproductionReceipt,
)


class ArtifactReader(Protocol):
    def get_bytes(self, digest: str) -> bytes: ...


def manifest_hash(manifest: EvidenceManifest) -> str:
    return sha256(manifest)


def create_receipt(
    manifest: EvidenceManifest, *, receipt_id: str = "evidence-receipt"
) -> EvidenceReceipt:
    bound_manifest_hash = manifest_hash(manifest)
    payload = {
        "receipt_id": receipt_id,
        "manifest_hash": bound_manifest_hash,
        "artifact_hashes": manifest.artifact_hashes,
        "integrity_not_truth": True,
    }
    return EvidenceReceipt(
        receipt_id=receipt_id,
        manifest_hash=bound_manifest_hash,
        artifact_hashes=manifest.artifact_hashes,
        receipt_hash=sha256(payload),
    )


def verify_receipt(
    receipt: EvidenceReceipt,
    manifest: EvidenceManifest,
    artifact_store: ArtifactReader,
    *,
    registered_artifacts: Mapping[str, Any] | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """Verify bytes and optional DB registration. A pass proves custody, never truth."""
    errors: list[str] = []
    expected_manifest_hash = manifest_hash(manifest)
    if receipt.manifest_hash != expected_manifest_hash:
        errors.append("manifest hash mismatch")
    expected_receipt_hash = sha256(
        {
            "receipt_id": receipt.receipt_id,
            "manifest_hash": receipt.manifest_hash,
            "artifact_hashes": receipt.artifact_hashes,
            "integrity_not_truth": True,
        }
    )
    if receipt.receipt_hash != expected_receipt_hash:
        errors.append("receipt hash mismatch")
    if tuple(receipt.artifact_hashes) != tuple(manifest.artifact_hashes):
        errors.append("receipt artifact list does not match manifest")
    for digest in manifest.artifact_hashes:
        try:
            content = artifact_store.get_bytes(digest)
        except (FileNotFoundError, ValueError, RuntimeError):
            errors.append(f"missing or unreadable artifact: {digest}")
            continue
        if sha256_bytes(content) != digest:
            errors.append(f"artifact hash mismatch: {digest}")
        if registered_artifacts is not None:
            registered = registered_artifacts.get(digest)
            if registered is None:
                errors.append(f"artifact is absent from DB registry: {digest}")
            elif isinstance(registered, Mapping):
                database_digests = [
                    registered[key]
                    for key in ("digest", "content_digest")
                    if key in registered
                ]
                if not database_digests or any(
                    value != digest for value in database_digests
                ):
                    errors.append(f"DB/artifact mismatch: {digest}")
            elif registered != digest:
                errors.append(f"DB/artifact mismatch: {digest}")
    return not errors, tuple(errors)


def verify_evidence(
    receipt: EvidenceReceipt,
    manifest: EvidenceManifest,
    artifact_store: ArtifactReader,
    *,
    evidence_type: str,
    verifier_id: str,
    verifier_digest: str,
    registered_artifacts: Mapping[str, Any] | None = None,
) -> EvidenceVerification:
    """Create an integrity result from real receipt/artifact verification, not caller assertion."""
    valid, errors = verify_receipt(
        receipt, manifest, artifact_store, registered_artifacts=registered_artifacts
    )
    return EvidenceVerification(
        evidence_type=evidence_type,
        receipt_id=receipt.receipt_id,
        receipt_hash=sha256(receipt),
        manifest_hash=manifest_hash(manifest),
        verifier_id=verifier_id,
        verifier_digest=verifier_digest,
        verified=valid,
        errors=errors,
    )


def build_reproduction_receipt(
    *,
    receipt_id: str,
    original_operator_id: str,
    original_authority_id: str,
    reproducer_operator_id: str,
    reproducer_authority_id: str,
    original_environment_hash: str,
    reproducer_environment_hash: str,
    original_manifest_hash: str,
    reproduced_manifest_hash: str,
    deviations: tuple[str, ...] = (),
    request_independent: bool = False,
) -> ReproductionReceipt:
    if request_independent:
        raise ValueError(
            "a reproduction receipt cannot self-assert independent validation"
        )
    return ReproductionReceipt(
        receipt_id=receipt_id,
        original_operator_id=original_operator_id,
        original_authority_id=original_authority_id,
        reproducer_operator_id=reproducer_operator_id,
        reproducer_authority_id=reproducer_authority_id,
        original_environment_hash=original_environment_hash,
        reproducer_environment_hash=reproducer_environment_hash,
        original_manifest_hash=original_manifest_hash,
        reproduced_manifest_hash=reproduced_manifest_hash,
        deviations=deviations,
    )
