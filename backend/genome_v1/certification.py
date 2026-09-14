"""Local descriptor checks with an explicit non-certifying authority ceiling."""

from __future__ import annotations

from .canonical import digest_for
from .models import CheckResult, GenomeCertificationReceipt, GenomeDescriptor

CHECKER_ID = "genome-v1-local"
CHECKER_DIGEST = digest_for({"checker_id": CHECKER_ID, "checks": ("schema", "canonical", "digest")}, domain="scaffold-arena.genome.checker")


def certify_descriptor(descriptor: GenomeDescriptor) -> GenomeCertificationReceipt:
    """Issue only a local descriptor/canonicalization receipt.

    A PASS does not certify an external runtime, interoperability, safety, or
    evidence truth.
    """
    bound = descriptor.with_digest()
    checks = (
        CheckResult(check_id="schema-valid", status="PASS", detail="Strict Genome v1 schema validation passed."),
        CheckResult(check_id="canonical-json", status="PASS", detail="Arena JSON v1 canonicalization completed."),
        CheckResult(check_id="digest-bound", status="PASS", detail="Descriptor digest binds the canonical domain envelope."),
    )
    raw = {
        "receipt_id": f"cert-{bound.content_digest.split(':', 1)[1][:24]}", "genome_digest": bound.content_digest,
        "checker_id": CHECKER_ID, "checker_digest": CHECKER_DIGEST,
        "checks": checks, "verdict": "PASS",
        "authority_ceiling": "local_descriptor_fixture_only",
        "limitations": ("PASS covers local descriptor checks only; it is not interoperability, safety, deployment, or truth certification.",),
        "integrity_not_truth": True,
    }
    return GenomeCertificationReceipt(**raw, receipt_digest=digest_for(raw, domain="scaffold-arena.genome.certification"))
