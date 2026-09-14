from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from artifacts_v1 import ArtifactIntegrityError, LocalArtifactStore


def test_dedup_and_tamper_detection(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    digest = store.put_bytes(b"hello")
    assert digest == store.put_bytes(b"hello")
    assert store.get_bytes(digest) == b"hello"
    Path(store.uri_for(digest)).write_bytes(b"tampered")
    with pytest.raises(ArtifactIntegrityError, match="does not match"):
        store.get_bytes(digest)


def test_traversal_and_symlink_escapes_are_rejected(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError):
        store.get_bytes("../not-a-digest")
    digest = hashlib.sha256(b"x").hexdigest()
    path = Path(store.uri_for(digest))
    path.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.write_bytes(b"x")
    path.symlink_to(outside)
    with pytest.raises(ArtifactIntegrityError, match="symlink"):
        store.get_bytes(digest)


def test_atomic_write_leaves_no_partial_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    import artifacts_v1.store as module

    def fail_link(*_args, **_kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr(module.os, "link", fail_link)
    with pytest.raises(OSError):
        store.put_bytes(b"never-published")
    assert not list((tmp_path / "artifacts").rglob(".artifact-*"))
    sha_root = tmp_path / "artifacts" / "sha256"
    if sha_root.exists():
        assert not any(path.is_file() for path in sha_root.rglob("*"))
