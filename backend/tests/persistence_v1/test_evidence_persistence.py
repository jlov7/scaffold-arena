from __future__ import annotations

import pytest

from persistence_v1 import (
    ArenaRepository,
    ImmutableReceiptConflict,
    create_persistence_engine,
    metadata,
)


def test_evidence_repository_requires_registered_artifacts_and_exact_replay(tmp_path) -> None:
    engine = create_persistence_engine(f"sqlite:///{tmp_path / 'arena.db'}")
    metadata.create_all(engine)
    repository = ArenaRepository(engine)
    repository.create_project("Personal", project_id="personal")
    digest = "a" * 64
    repository.register_artifact(digest, size_bytes=1, storage_uri="test://artifact")
    arguments = {
        "receipt_id": "receipt-one", "receipt_hash": "b" * 64, "manifest_hash": "c" * 64,
        "manifest_json": {"manifest": "hash-only"}, "artifact_hashes": (digest,), "evidence_type": "fixture",
        "claim_ceiling": "custody only", "execution_id": None,
    }
    assert repository.create_evidence_receipt("personal", **arguments) is False
    assert repository.create_evidence_receipt("personal", **arguments) is True
    with pytest.raises(ImmutableReceiptConflict):
        repository.create_evidence_receipt("personal", **{**arguments, "claim_ceiling": "changed"})
