"""Explicit, offline-only archive admission for digest-bound adapter artifacts.

Validation never executes an archive and never fetches a package.  Operators
must supply immutable bytes and an expected SHA-256 before this module creates
an atomically published content-addressed extraction.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tarfile
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class OfflineInstallHold(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message); self.code = code


MAX_FILES = 256
MAX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_COMPRESSED_BYTES = 8 * 1024 * 1024
MAX_RATIO = 100


@dataclass(frozen=True)
class VerifiedArchive:
    digest: str
    file_count: int
    uncompressed_bytes: int
    extracted_root: Path
    inventory_digest: str
    identity_binding: "ArchiveIdentityBinding"
    executed: bool = False


@dataclass(frozen=True)
class ArchiveIdentityBinding:
    """Content-addressed identity needed by any later, separate admission."""

    archive_digest: str
    executable_path: str
    executable_digest: str
    manifest_path: str
    manifest_digest: str
    runtime_digest: str
    profile_digest: str

    def validate(self) -> None:
        values = (self.archive_digest, self.executable_digest, self.manifest_digest, self.runtime_digest, self.profile_digest)
        if any(not value.startswith("sha256:") or len(value) != 71 or any(char not in "0123456789abcdef" for char in value[7:]) for value in values):
            raise OfflineInstallHold("archive_identity_binding_invalid", "Archive identity bindings require lowercase SHA-256 digests.")
        for path in (self.executable_path, self.manifest_path):
            safe = PurePosixPath(path)
            if safe.is_absolute() or any(part in {"", ".", ".."} for part in safe.parts):
                raise OfflineInstallHold("archive_identity_binding_invalid", "Executable and manifest paths must be safe relative POSIX paths.")


def _safe_member(name: str, seen: set[str]) -> PurePosixPath:
    if not name or "\x00" in name or "\\" in name:
        raise OfflineInstallHold("archive_path_invalid", "Archive members must have safe relative POSIX paths.")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise OfflineInstallHold("archive_path_escape", "Archive members cannot traverse outside the extraction root.")
    rendered = unicodedata.normalize("NFC", path.as_posix()).casefold()
    if rendered in seen:
        raise OfflineInstallHold("archive_name_collision", "Archive members cannot collide under Unicode or case-insensitive filesystems.")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{number}" for number in range(1, 10)), *(f"LPT{number}" for number in range(1, 10))}
    if any(part.rstrip(". ").split(".", 1)[0].upper() in reserved or ":" in part for part in path.parts):
        raise OfflineInstallHold("archive_windows_name", "Archive members cannot use Windows reserved or NTFS stream names.")
    seen.add(rendered)
    return path


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _private_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise OfflineInstallHold("archive_cache_untrusted", "Offline archive publication requires an owner-private, non-symlink cache directory.")
    return path


def _check_limits(count: int, total: int, compressed: int) -> None:
    if count > MAX_FILES or total > MAX_UNCOMPRESSED_BYTES:
        raise OfflineInstallHold("archive_size_limit", "The archive exceeds the bounded file or uncompressed-byte limit.")
    if total and compressed and total > compressed * MAX_RATIO:
        raise OfflineInstallHold("archive_compression_ratio", "The archive exceeds the permitted decompression ratio.")


def _consume(source: object, maximum: int) -> int:
    """Read a member fully while enforcing the limit used by admission."""
    total = 0
    while True:
        chunk = source.read(min(64 * 1024, maximum - total + 1))  # type: ignore[attr-defined]
        if not chunk:
            return total
        total += len(chunk)
        if total > maximum:
            raise OfflineInstallHold("archive_size_limit", "An archive member exceeds the bounded uncompressed-byte limit.")


def _scan_zip(raw: bytes) -> tuple[int, int]:
    seen: set[str] = set(); total = 0; compressed = 0
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > MAX_FILES:
                raise OfflineInstallHold("archive_size_limit", "The archive exceeds the bounded file limit.")
            for index, item in enumerate(members, 1):
                _safe_member(item.filename.rstrip("/"), seen)
                if item.is_dir():
                    continue
                if item.flag_bits & 0x1:
                    raise OfflineInstallHold("archive_encrypted", "Encrypted archive members are not allowed.")
                kind = stat.S_IFMT(item.external_attr >> 16)
                if kind in {stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO}:
                    raise OfflineInstallHold("archive_special_member", "Archive links and special files are not allowed.")
                total += item.file_size; compressed += item.compress_size
                _check_limits(index, total, max(1, compressed))
                try:
                    with archive.open(item) as input_handle:
                        if _consume(input_handle, item.file_size) != item.file_size:
                            raise OfflineInstallHold("archive_member_unreadable", "An archive member ended before its declared size.")
                except (RuntimeError, OSError, zipfile.BadZipFile) as exc:
                    raise OfflineInstallHold("archive_member_unreadable", "A ZIP archive member could not be read safely.") from exc
    except zipfile.BadZipFile as exc:
        raise OfflineInstallHold("archive_invalid", "The supplied ZIP archive is invalid.") from exc
    return len(seen), total


def _scan_tar(raw: bytes) -> tuple[int, int]:
    seen: set[str] = set(); total = 0
    try:
        with tarfile.open(fileobj=__import__("io").BytesIO(raw), mode="r:*") as archive:
            members = archive.getmembers()
            if len(members) > MAX_FILES:
                raise OfflineInstallHold("archive_size_limit", "The archive exceeds the bounded file limit.")
            for index, item in enumerate(members, 1):
                if not item.isfile():
                    if item.isdir(): continue
                    raise OfflineInstallHold("archive_special_member", "Archive links, devices, FIFOs, and sparse members are not allowed.")
                _safe_member(item.name, seen)
                if getattr(item, "sparse", None):
                    raise OfflineInstallHold("archive_sparse_member", "Sparse archive members are not allowed.")
                total += item.size; _check_limits(index, total, len(raw))
                input_handle = archive.extractfile(item)
                if input_handle is None:
                    raise OfflineInstallHold("archive_member_unreadable", "A TAR archive member could not be read safely.")
                with input_handle:
                    if _consume(input_handle, item.size) != item.size:
                        raise OfflineInstallHold("archive_member_unreadable", "An archive member ended before its declared size.")
    except tarfile.TarError as exc:
        raise OfflineInstallHold("archive_invalid", "The supplied TAR archive is invalid.") from exc
    return len(seen), total


def verify_offline_archive(archive: Path, expected_sha256: str) -> tuple[bytes, int, int]:
    """Read source bytes once, bind their digest, and scan before extraction."""
    if len(expected_sha256) != 64 or any(char not in "0123456789abcdef" for char in expected_sha256):
        raise OfflineInstallHold("archive_digest_invalid", "An explicit lowercase SHA-256 is required.")
    try:
        if archive.stat().st_size > MAX_COMPRESSED_BYTES:
            raise OfflineInstallHold("archive_input_limit", "The archive compressed input exceeds the byte limit.")
        with archive.open("rb") as handle:
            raw = handle.read(MAX_COMPRESSED_BYTES + 1)
        if len(raw) > MAX_COMPRESSED_BYTES:
            raise OfflineInstallHold("archive_input_limit", "The archive compressed input exceeds the byte limit.")
    except OSError as exc:
        raise OfflineInstallHold("archive_unreadable", "The operator-supplied archive cannot be read.") from exc
    if _sha256_bytes(raw) != expected_sha256:
        raise OfflineInstallHold("archive_digest_mismatch", "The archive bytes do not match the expected SHA-256.")
    suffix = archive.name.casefold()
    if suffix.endswith(".zip"):
        count, size = _scan_zip(raw)
    elif suffix.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")):
        count, size = _scan_tar(raw)
    else:
        raise OfflineInstallHold("archive_format_unsupported", "Only explicit ZIP or TAR archives are accepted.")
    return raw, count, size


def install_verified_archive(archive: Path, expected_sha256: str, cache_root: Path, *, identity_binding: ArchiveIdentityBinding | None = None) -> VerifiedArchive:
    """Extract a verified snapshot atomically under cache/sha256/<digest>.

    The original path is not reopened after validation, defeating path/inode
    substitution between validation and extraction.
    """
    raw, count, size = verify_offline_archive(archive, expected_sha256)
    if identity_binding is None:
        raise OfflineInstallHold("archive_identity_binding_required", "No executable archive admission is available without typed archive, executable, manifest, runtime, and profile bindings.")
    identity_binding.validate()
    if identity_binding.archive_digest != f"sha256:{expected_sha256}":
        raise OfflineInstallHold("archive_identity_binding_mismatch", "The typed archive binding does not match the verified archive bytes.")
    root = _private_directory(cache_root.absolute())
    parent = _private_directory(root / "sha256")
    target = parent / expected_sha256
    if os.path.lexists(target):
        raise OfflineInstallHold("archive_cache_exists", "A pre-existing cache target is not trusted without a separately verified receipt.")
    locks = _private_directory(parent / ".locks")
    lock = locks / expected_sha256
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
    except FileExistsError as exc:
        raise OfflineInstallHold("archive_publish_in_progress", "A matching archive cache publish is already in progress; retry after verifying its receipt.") from exc
    temporary = Path(tempfile.mkdtemp(prefix=".adapter-", dir=target.parent))
    reserved = False
    try:
        if archive.name.casefold().endswith(".zip"):
            with zipfile.ZipFile(__import__("io").BytesIO(raw)) as source:
                for item in source.infolist():
                    if item.is_dir(): continue
                    destination = temporary / _safe_member(item.filename, set())
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        with source.open(item) as input_handle, destination.open("xb") as output_handle:
                            shutil.copyfileobj(input_handle, output_handle)
                    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                        raise OfflineInstallHold("archive_member_unreadable", "A verified archive member could not be read safely.") from exc
        else:
            with tarfile.open(fileobj=__import__("io").BytesIO(raw), mode="r:*") as source:
                for item in source.getmembers():
                    if not item.isfile(): continue
                    destination = temporary / _safe_member(item.name, set())
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    input_handle = source.extractfile(item)
                    if input_handle is None: raise OfflineInstallHold("archive_invalid", "Archive member cannot be read.")
                    with input_handle, destination.open("xb") as output_handle: shutil.copyfileobj(input_handle, output_handle)
        # mkdir is an atomic no-replace reservation.  We never rename over a
        # content-addressed cache path, even when a concurrent publisher races.
        try:
            os.mkdir(target, mode=0o700)
            reserved = True
        except FileExistsError as exc:
            raise OfflineInstallHold("archive_publish_race", "A cache target appeared during extraction; it was not accepted.") from exc
        payload = target / "payload"
        os.rename(temporary, payload)
        for path, digest, label in ((identity_binding.executable_path, identity_binding.executable_digest, "executable"), (identity_binding.manifest_path, identity_binding.manifest_digest, "manifest")):
            candidate = payload / path
            if candidate.is_symlink() or not candidate.is_file() or f"sha256:{_sha256_bytes(candidate.read_bytes())}" != digest:
                raise OfflineInstallHold("archive_identity_binding_mismatch", f"The declared {label} bytes do not match the typed identity binding.")
        inventory = {
            "schema": "scaffold-arena.offline-archive-inventory/1",
            "archive_digest": f"sha256:{expected_sha256}",
            "file_count": count,
            "uncompressed_bytes": size,
            "payload_tree_digest": _tree_digest(payload),
            "identity_binding": {
                "archive_digest": identity_binding.archive_digest,
                "executable_path": identity_binding.executable_path,
                "executable_digest": identity_binding.executable_digest,
                "manifest_path": identity_binding.manifest_path,
                "manifest_digest": identity_binding.manifest_digest,
                "runtime_digest": identity_binding.runtime_digest,
                "profile_digest": identity_binding.profile_digest,
            },
        }
        inventory_bytes = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
        with (target / "inventory.json").open("xb") as receipt:
            receipt.write(inventory_bytes)
        return VerifiedArchive(expected_sha256, count, size, payload, f"sha256:{_sha256_bytes(inventory_bytes)}", identity_binding)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        if reserved:
            shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        lock.unlink(missing_ok=True)


def _tree_digest(root: Path) -> str:
    entries: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            raise OfflineInstallHold("archive_publish_invalid", "Published archive payload contains an unexpected filesystem object.")
        entries.append((path.relative_to(root).as_posix(), _sha256_bytes(path.read_bytes())))
    return f"sha256:{_sha256_bytes(json.dumps(entries, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))}"
