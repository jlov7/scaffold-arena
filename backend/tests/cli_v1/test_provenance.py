from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from adapters_v1.offline_fixture import bundled_study_pack_root
from arena_cli.cli import main
from arena_cli.provenance import collect_study_pack_provenance


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "Provenance Test")
    _git(root, "config", "user.email", "provenance@example.test")
    (root / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    return root


def test_study_pack_provenance_is_stable_secret_free_and_dirty_sensitive(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _repository(tmp_path)
    pack_path = bundled_study_pack_root() / "study-pack.json"
    captured_at = datetime(2026, 8, 17, 1, 2, 3, tzinfo=UTC)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-not-capture-this-secret")

    first = collect_study_pack_provenance(
        repository_root=root,
        study_pack_path=pack_path,
        captured_at=captured_at,
    )
    second = collect_study_pack_provenance(
        repository_root=root,
        study_pack_path=pack_path,
        captured_at=captured_at,
    )

    assert first.provenance == second.provenance
    assert first.repository_dirty is False
    assert first.provenance.code_revision == _git(root, "rev-parse", "HEAD")
    assert first.provenance.captured_at == captured_at
    assert len(first.provenance.source_refs) >= 2
    serialized = json.dumps(first.model_dump(mode="json"), sort_keys=True)
    assert "do-not-capture-this-secret" not in serialized
    assert str(root) not in serialized

    (root / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    dirty = collect_study_pack_provenance(
        repository_root=root,
        study_pack_path=pack_path,
        captured_at=captured_at,
    )
    assert dirty.repository_dirty is True
    assert dirty.provenance.code_revision == first.provenance.code_revision
    assert dirty.provenance.code_hash != first.provenance.code_hash
    assert dirty.provenance.environment_hash == first.provenance.environment_hash


def test_provenance_never_hashes_sensitive_or_symlinked_untracked_content(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    pack_path = bundled_study_pack_root() / "study-pack.json"
    captured_at = datetime(2026, 8, 17, 1, 2, 3, tzinfo=UTC)
    external = tmp_path / "outside-secret.txt"
    external.write_text("outside-secret-alpha", encoding="utf-8")
    (root / ".env").write_text("API_KEY=inside-secret-alpha\n", encoding="utf-8")
    (root / "linked-secret.txt").symlink_to(external)
    (root / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")

    first = collect_study_pack_provenance(
        repository_root=root,
        study_pack_path=pack_path,
        captured_at=captured_at,
    )
    (root / ".env").write_text("API_KEY=inside-secret-beta\n", encoding="utf-8")
    external.write_text("outside-secret-beta", encoding="utf-8")
    second = collect_study_pack_provenance(
        repository_root=root,
        study_pack_path=pack_path,
        captured_at=captured_at,
    )

    assert first.repository_dirty is True
    assert first.provenance.code_hash == second.provenance.code_hash

    (root / "feature.py").write_text("VALUE = 2\n", encoding="utf-8")
    third = collect_study_pack_provenance(
        repository_root=root,
        study_pack_path=pack_path,
        captured_at=captured_at,
    )
    assert third.provenance.code_hash != second.provenance.code_hash


def test_provenance_rejects_symlinked_dependency_lockfiles(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    pack_path = bundled_study_pack_root() / "study-pack.json"
    external = tmp_path / "outside-package-lock.json"
    external.write_text('{"token":"outside-secret"}\n', encoding="utf-8")
    (root / "package-lock.json").symlink_to(external)

    with pytest.raises(ValueError, match="dependency lockfile must be a regular in-tree file"):
        collect_study_pack_provenance(
            repository_root=root,
            study_pack_path=pack_path,
        )


def test_unversioned_provenance_rejects_oversized_source_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "unversioned-source"
    root.mkdir()
    (root / "module.py").write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    pack_path = bundled_study_pack_root() / "study-pack.json"

    with pytest.raises(ValueError, match="source file exceeds the provenance capture limit"):
        collect_study_pack_provenance(
            repository_root=root,
            study_pack_path=pack_path,
        )


def test_provenance_capture_cli_emits_machine_readable_json(
    tmp_path: Path,
    capsys,
) -> None:
    root = _repository(tmp_path)
    pack_path = bundled_study_pack_root() / "study-pack.json"
    output = tmp_path / "provenance.json"

    assert main(
        [
            "provenance",
            "capture",
            "--root",
            str(root),
            "--study-pack",
            str(pack_path),
            "--output",
            str(output),
        ]
    ) == 0
    emitted = json.loads(capsys.readouterr().out)
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert emitted["verdict"] == "PASS"
    assert emitted["provider_execution_started"] is False
    assert emitted["provenance"] == persisted["provenance"]
    assert persisted["capture_method"] == "automatic-local-v1"
    assert persisted["limitations"]
