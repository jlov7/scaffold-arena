from __future__ import annotations

from .models import EvidenceManifest, RedactedArtifactDescriptor, RedactedExportManifest
from .receipts import manifest_hash


def redacted_export(
    manifest: EvidenceManifest, *, reason: str = "artifact content withheld"
) -> RedactedExportManifest:
    """Export only hashes and explicitly withheld descriptors; values never leave this boundary."""
    return RedactedExportManifest(
        manifest_hash=manifest_hash(manifest),
        evidence_class=manifest.evidence_class,
        claim_ceiling=manifest.claim_ceiling,
        evaluator_hashes=manifest.evaluator_hashes,
        artifacts=tuple(
            RedactedArtifactDescriptor(
                original_hash=digest, disposition="withheld", reason=reason
            )
            for digest in manifest.artifact_hashes
        ),
    )
