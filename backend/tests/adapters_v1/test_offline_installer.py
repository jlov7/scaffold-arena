from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile

import pytest

from adapters_v1.offline_installer import ArchiveIdentityBinding, OfflineInstallHold, install_verified_archive, verify_offline_archive


def _write(tmp_path, name: str, raw: bytes):
    path = tmp_path / name; path.write_bytes(raw); return path, hashlib.sha256(raw).hexdigest()


def _zip(entries: dict[str, bytes], *, symlink: bool = False) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            item = zipfile.ZipInfo(name)
            item.compress_type = zipfile.ZIP_DEFLATED
            if symlink: item.external_attr = 0o120777 << 16
            archive.writestr(item, value)
    return output.getvalue()


def _binding(archive_digest: str, entries: dict[str, bytes]) -> ArchiveIdentityBinding:
    return ArchiveIdentityBinding(
        archive_digest=f"sha256:{archive_digest}", executable_path="bin/agent", executable_digest=f"sha256:{hashlib.sha256(entries['bin/agent']).hexdigest()}",
        manifest_path="manifest.json", manifest_digest=f"sha256:{hashlib.sha256(entries['manifest.json']).hexdigest()}",
        runtime_digest="sha256:" + "a" * 64, profile_digest="sha256:" + "b" * 64,
    )


@pytest.mark.parametrize("entries", [{"../escape": b"x"}, {"A": b"x", "a": b"y"}])
def test_zip_rejects_path_escape_and_case_collisions(tmp_path, entries) -> None:
    path, digest = _write(tmp_path, "bad.zip", _zip(entries))
    with pytest.raises(OfflineInstallHold): verify_offline_archive(path, digest)


def test_zip_rejects_symlink_and_decompression_bomb(tmp_path) -> None:
    path, digest = _write(tmp_path, "link.zip", _zip({"link": b"target"}, symlink=True))
    with pytest.raises(OfflineInstallHold): verify_offline_archive(path, digest)
    path, digest = _write(tmp_path, "bomb.zip", _zip({"large": b"0" * (2 * 1024 * 1024)}))
    with pytest.raises(OfflineInstallHold): verify_offline_archive(path, digest)


def test_tar_rejects_links_devices_and_fifo(tmp_path) -> None:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        member = tarfile.TarInfo("link"); member.type = tarfile.SYMTYPE; member.linkname = "target"; archive.addfile(member)
    path, digest = _write(tmp_path, "bad.tar", raw.getvalue())
    with pytest.raises(OfflineInstallHold): verify_offline_archive(path, digest)


def test_verified_snapshot_is_digest_bound_and_not_executed(tmp_path) -> None:
    entries = {"bin/agent": b"not executed", "manifest.json": b"{}"}
    path, digest = _write(tmp_path, "fixture.zip", _zip(entries))
    installed = install_verified_archive(path, digest, tmp_path / "cache", identity_binding=_binding(digest, entries))
    assert installed.executed is False
    assert (installed.extracted_root / "bin/agent").read_bytes() == b"not executed"
    path.write_bytes(_zip({"bin/agent": b"replacement"}))
    assert (installed.extracted_root / "bin/agent").read_bytes() == b"not executed"


def test_cache_prepopulation_and_windows_device_names_are_rejected(tmp_path) -> None:
    path, digest = _write(tmp_path, "fixture.zip", _zip({"CON.txt": b"x"}))
    with pytest.raises(OfflineInstallHold): verify_offline_archive(path, digest)
    entries = {"bin/agent": b"x", "manifest.json": b"{}"}
    path, digest = _write(tmp_path, "safe.zip", _zip(entries))
    target = tmp_path / "cache" / "sha256" / digest; target.mkdir(parents=True)
    with pytest.raises(OfflineInstallHold, match="pre-existing"):
        install_verified_archive(path, digest, tmp_path / "cache", identity_binding=_binding(digest, entries))


@pytest.mark.parametrize("name", ["COM2.txt", "COM9.log", "LPT2.md", "LPT9.json"])
def test_windows_reserved_name_extensions_are_rejected(tmp_path, name: str) -> None:
    path, digest = _write(tmp_path, "reserved.zip", _zip({name: b"x"}))
    with pytest.raises(OfflineInstallHold) as held:
        verify_offline_archive(path, digest)
    assert held.value.code == "archive_windows_name"


def test_tar_gzip_bomb_and_cache_symlink_are_rejected(tmp_path) -> None:
    bomb = io.BytesIO()
    with tarfile.open(fileobj=bomb, mode="w:gz") as archive:
        member = tarfile.TarInfo("large")
        member.size = 2 * 1024 * 1024
        archive.addfile(member, io.BytesIO(b"0" * member.size))
    path, digest = _write(tmp_path, "bomb.tar.gz", bomb.getvalue())
    with pytest.raises(OfflineInstallHold) as held:
        verify_offline_archive(path, digest)
    assert held.value.code == "archive_compression_ratio"

    entries = {"bin/agent": b"x", "manifest.json": b"{}"}
    path, digest = _write(tmp_path, "safe.zip", _zip(entries))
    target = tmp_path / "cache" / "sha256" / digest
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "attacker-cache")
    with pytest.raises(OfflineInstallHold) as held:
        install_verified_archive(path, digest, tmp_path / "cache", identity_binding=_binding(digest, entries))
    assert held.value.code == "archive_cache_exists"


def test_install_writes_digest_bound_inventory(tmp_path) -> None:
    entries = {"bin/agent": b"not executed", "manifest.json": b"{}"}
    path, digest = _write(tmp_path, "fixture.zip", _zip(entries))
    installed = install_verified_archive(path, digest, tmp_path / "cache", identity_binding=_binding(digest, entries))
    receipt = installed.extracted_root.parent / "inventory.json"
    assert installed.inventory_digest == f"sha256:{hashlib.sha256(receipt.read_bytes()).hexdigest()}"
    assert f'"archive_digest":"sha256:{digest}"' in receipt.read_text()
    assert '"runtime_digest":"sha256:' in receipt.read_text()


def test_install_holds_without_complete_or_matching_identity_binding(tmp_path) -> None:
    entries = {"bin/agent": b"not executed", "manifest.json": b"{}"}
    path, digest = _write(tmp_path, "fixture.zip", _zip(entries))
    with pytest.raises(OfflineInstallHold) as held:
        install_verified_archive(path, digest, tmp_path / "cache")
    assert held.value.code == "archive_identity_binding_required"
    bad = _binding(digest, entries).__class__(**{**_binding(digest, entries).__dict__, "executable_digest": "sha256:" + "f" * 64})
    with pytest.raises(OfflineInstallHold) as held:
        install_verified_archive(path, digest, tmp_path / "cache", identity_binding=bad)
    assert held.value.code == "archive_identity_binding_mismatch"
