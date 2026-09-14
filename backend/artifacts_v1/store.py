from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse


class ArtifactIntegrityError(RuntimeError):
    pass


class ArtifactStore(Protocol):
    def put_bytes(self, content: bytes, *, media_type: str = "application/octet-stream", metadata: Mapping[str, str] | None = None) -> str: ...
    def get_bytes(self, digest: str) -> bytes: ...
    def uri_for(self, digest: str) -> str: ...


def _validate_digest(digest: str) -> None:
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("digest must be a lowercase SHA-256 hex value")


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class LocalArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        _validate_digest(digest)
        path = self.root / "sha256" / digest[:2] / digest
        parent = path.parent.resolve()
        if self.root not in (parent, *parent.parents):
            raise ArtifactIntegrityError("artifact path escapes configured root")
        if path.exists() and path.is_symlink():
            raise ArtifactIntegrityError("symlink artifacts are not allowed")
        return path

    def put_bytes(self, content: bytes, *, media_type: str = "application/octet-stream", metadata: Mapping[str, str] | None = None) -> str:
        del media_type, metadata
        digest = _digest(content)
        target = self._path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if self.get_bytes(digest) != content:
                raise ArtifactIntegrityError("digest path already contains mismatched content")
            return digest
        descriptor, temporary_name = tempfile.mkstemp(prefix=".artifact-", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                if self.get_bytes(digest) != content:
                    raise ArtifactIntegrityError("digest path already contains mismatched content")
            return digest
        finally:
            temporary.unlink(missing_ok=True)

    def get_bytes(self, digest: str) -> bytes:
        path = self._path(digest)
        if not path.exists():
            raise FileNotFoundError(digest)
        resolved = path.resolve(strict=True)
        if self.root not in (resolved, *resolved.parents) or resolved.is_symlink():
            raise ArtifactIntegrityError("artifact path escapes configured root")
        content = resolved.read_bytes()
        if _digest(content) != digest:
            raise ArtifactIntegrityError("artifact content does not match its digest")
        return content

    def uri_for(self, digest: str) -> str:
        return str(self._path(digest))


_BUCKET = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{1,61}[a-z0-9])$")
_PREFIX_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _safe_bucket(bucket: str) -> str:
    if not _BUCKET.fullmatch(bucket) or ".." in bucket or ".-" in bucket or "-." in bucket:
        raise ValueError("bucket must be a bounded S3-compatible bucket name")
    return bucket


def _safe_prefix(prefix: str) -> str:
    if not prefix:
        raise ValueError("prefix must contain one or more relative safe path segments")
    if len(prefix) > 512 or prefix.startswith("/") or prefix.endswith("/") or "\\" in prefix:
        raise ValueError("prefix must contain relative safe path segments")
    segments = prefix.split("/")
    if any(len(segment) > 128 or segment in {"", ".", ".."} or not _PREFIX_SEGMENT.fullmatch(segment) for segment in segments):
        raise ValueError("prefix must contain relative safe path segments")
    return prefix


def _is_literal_loopback(host: str | None) -> bool:
    if host is None:
        return False
    if host.lower() in _LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _safe_endpoint(endpoint_url: str) -> str:
    parsed = urlparse(endpoint_url)
    if not parsed.scheme or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("endpoint_url must be an explicit credential-free HTTP(S) endpoint")
    if parsed.scheme == "https":
        return endpoint_url.rstrip("/")
    if parsed.scheme == "http" and _is_literal_loopback(parsed.hostname):
        return endpoint_url.rstrip("/")
    raise ValueError("endpoint_url must use HTTPS unless it is a literal loopback test/development endpoint")


def _error_code(error: BaseException) -> str | None:
    response = getattr(error, "response", None)
    if not isinstance(response, Mapping):
        return None
    failure = response.get("Error")
    return str(failure.get("Code")) if isinstance(failure, Mapping) and failure.get("Code") is not None else None


class S3CompatibleArtifactStore:
    """Fail-closed, content-addressed S3-compatible artifact storage.

    This adapter deliberately owns only object bytes and service-owned integrity
    metadata. Artifact classification and other content metadata stay in the
    database record. Construction accepts an injected transport so tests never
    need credentials or a network connection.
    """

    _READ_CHUNK_SIZE = 64 * 1024

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str,
        region_name: str,
        prefix: str,
        path_style: bool = False,
        max_artifact_bytes: int = 32 * 1024 * 1024,
        client: Any | None = None,
        client_factory: Callable[..., Any] | None = None,
    ):
        if not region_name or not region_name.strip():
            raise ValueError("region_name must be explicit and nonempty")
        if max_artifact_bytes <= 0:
            raise ValueError("max_artifact_bytes must be positive")
        if client is not None and client_factory is not None:
            raise ValueError("supply either client or client_factory, not both")
        self.bucket = _safe_bucket(bucket)
        self.prefix = _safe_prefix(prefix)
        self.endpoint_url = _safe_endpoint(endpoint_url)
        self.region_name = region_name.strip()
        self.path_style = path_style
        self.max_artifact_bytes = max_artifact_bytes
        self._s3: Any | None = client
        self._client_factory = client_factory

    def _client(self) -> Any:
        if self._s3 is not None:
            return self._s3
        if self._client_factory is not None:
            try:
                self._s3 = self._client_factory(
                    endpoint_url=self.endpoint_url,
                    region_name=self.region_name,
                    path_style=self.path_style,
                )
            except Exception:  # noqa: BLE001 - external transport errors must be redacted at this boundary
                raise ArtifactIntegrityError("artifact transport could not be initialized") from None
            return self._s3
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            raise ArtifactIntegrityError("S3-compatible artifact support requires the team deployment dependency") from None
        try:
            self._s3 = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                region_name=self.region_name,
                config=Config(s3={"addressing_style": "path" if self.path_style else "auto"}),
            )
        except Exception:  # noqa: BLE001 - external transport errors must be redacted at this boundary
            raise ArtifactIntegrityError("artifact transport could not be initialized") from None
        return self._s3

    def _key(self, digest: str) -> str:
        _validate_digest(digest)
        key = f"sha256/{digest[:2]}/{digest}"
        return f"{self.prefix}/{key}" if self.prefix else key

    def put_bytes(self, content: bytes, *, media_type: str = "application/octet-stream", metadata: Mapping[str, str] | None = None) -> str:
        del metadata
        if len(content) > self.max_artifact_bytes:
            raise ArtifactIntegrityError("artifact exceeds configured byte limit")
        digest = _digest(content)
        key = self._key(digest)
        try:
            self._client().put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType=media_type,
                Metadata={"sha256": digest},
                IfNoneMatch="*",
            )
        except Exception as error:  # noqa: BLE001 - external transport errors must be redacted at this boundary
            if _error_code(error) not in {"412", "PreconditionFailed", "ConditionalRequestConflict"}:
                raise ArtifactIntegrityError("artifact upload failed") from None
        try:
            persisted = self.get_bytes(digest)
        except (ArtifactIntegrityError, FileNotFoundError):
            raise ArtifactIntegrityError("artifact upload could not be verified") from None
        if persisted != content:
            raise ArtifactIntegrityError("artifact digest key contains mismatched content")
        return digest

    def _read_limited(self, response: Mapping[str, Any], digest: str) -> bytes:
        body = response.get("Body")
        try:
            if body is None or not callable(getattr(body, "read", None)):
                raise ArtifactIntegrityError("artifact response has no readable body")
            length = response.get("ContentLength")
            if not isinstance(length, int) or length < 0:
                raise ArtifactIntegrityError("artifact response has invalid content length")
            if length > self.max_artifact_bytes:
                raise ArtifactIntegrityError("artifact exceeds configured byte limit")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = body.read(min(self._READ_CHUNK_SIZE, self.max_artifact_bytes - total + 1))
                if not isinstance(chunk, bytes):
                    raise ArtifactIntegrityError("artifact response body is invalid")
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_artifact_bytes:
                    raise ArtifactIntegrityError("artifact exceeds configured byte limit")
                chunks.append(chunk)
            if total != length:
                raise ArtifactIntegrityError("artifact response length does not match declared length")
            content = b"".join(chunks)
            metadata = response.get("Metadata")
            if not isinstance(metadata, Mapping) or str(metadata.get("sha256", metadata.get("SHA256", ""))).lower() != digest:
                raise ArtifactIntegrityError("artifact metadata digest does not match key")
            if _digest(content) != digest:
                raise ArtifactIntegrityError("artifact content does not match its digest")
            return content
        except ArtifactIntegrityError:
            raise
        except Exception:  # noqa: BLE001 - external transport errors must be redacted at this boundary
            raise ArtifactIntegrityError("artifact response could not be read") from None
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                with suppress(Exception):
                    close()

    def get_bytes(self, digest: str) -> bytes:
        key = self._key(digest)
        try:
            response = self._client().get_object(Bucket=self.bucket, Key=key)
        except Exception as error:  # noqa: BLE001 - external transport errors must be redacted at this boundary
            if _error_code(error) in {"404", "NoSuchKey", "NotFound"}:
                raise FileNotFoundError(digest) from None
            raise ArtifactIntegrityError("artifact object could not be retrieved") from None
        if not isinstance(response, Mapping):
            raise ArtifactIntegrityError("artifact response is invalid")
        return self._read_limited(response, digest)

    def uri_for(self, digest: str) -> str:
        return f"s3://{self.bucket}/{self._key(digest)}"


# Backward-compatible import name for the original deployment adapter.
S3ArtifactStore = S3CompatibleArtifactStore
