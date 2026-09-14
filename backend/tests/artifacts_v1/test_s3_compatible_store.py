from __future__ import annotations

import hashlib
from typing import Any

import pytest

from artifacts_v1 import ArtifactIntegrityError, S3CompatibleArtifactStore


class FakeS3Error(Exception):
    def __init__(self, code: str, message: str = "transport failed") -> None:
        super().__init__(message)
        self.response = {"Error": {"Code": code}}


class FakeBody:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.offset = 0
        self.read_sizes: list[int] = []
        self.closed = False

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        result = self.content[self.offset:self.offset + size]
        self.offset += len(result)
        return result

    def close(self) -> None:
        self.closed = True


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, dict[str, str]]] = {}
        self.put_calls: list[dict[str, Any]] = []
        self.get_bodies: list[FakeBody] = []
        self.put_failure: BaseException | None = None
        self.store_before_failure = False

    def put_object(self, **kwargs: Any) -> None:
        self.put_calls.append(kwargs)
        if self.put_failure is not None:
            if self.store_before_failure:
                self.objects[str(kwargs["Key"])] = (bytes(kwargs["Body"]), dict(kwargs["Metadata"]))
            raise self.put_failure
        key = str(kwargs["Key"])
        if key in self.objects and kwargs.get("IfNoneMatch") == "*":
            raise FakeS3Error("PreconditionFailed")
        self.objects[key] = (bytes(kwargs["Body"]), dict(kwargs["Metadata"]))

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        del Bucket
        try:
            content, metadata = self.objects[Key]
        except KeyError:
            raise FakeS3Error("NoSuchKey") from None
        body = FakeBody(content)
        self.get_bodies.append(body)
        return {"Body": body, "ContentLength": len(content), "Metadata": metadata}


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def store(client: FakeS3, **kwargs: Any) -> S3CompatibleArtifactStore:
    return S3CompatibleArtifactStore(
        "arena-artifacts",
        endpoint_url="https://objects.example.test",
        region_name="us-test-1",
        prefix="team-a/artifacts",
        client=client,
        **kwargs,
    )


def test_put_uses_exact_content_addressed_key_and_only_service_metadata() -> None:
    client = FakeS3()
    artifact_store = store(client)
    content = b"immutable artifact"

    actual = artifact_store.put_bytes(content, media_type="application/json", metadata={"classification": "private", "secret": "never-store"})

    expected = digest(content)
    assert actual == expected
    call = client.put_calls[0]
    assert call["Key"] == f"team-a/artifacts/sha256/{expected[:2]}/{expected}"
    assert call["IfNoneMatch"] == "*"
    assert call["Metadata"] == {"sha256": expected}
    assert call["ContentType"] == "application/json"
    assert artifact_store.uri_for(expected) == f"s3://arena-artifacts/{call['Key']}"
    assert "secret" not in artifact_store.uri_for(expected)


def test_put_is_idempotent_and_verifies_existing_content() -> None:
    client = FakeS3()
    artifact_store = store(client)
    content = b"same content"

    assert artifact_store.put_bytes(content) == digest(content)
    assert artifact_store.put_bytes(content) == digest(content)
    assert len(client.put_calls) == 2


def test_duplicate_key_mismatch_fails_closed() -> None:
    client = FakeS3()
    artifact_store = store(client)
    content = b"expected"
    content_digest = digest(content)
    client.objects[f"team-a/artifacts/sha256/{content_digest[:2]}/{content_digest}"] = (b"corrupt", {"sha256": content_digest})

    with pytest.raises(ArtifactIntegrityError, match="could not be verified"):
        artifact_store.put_bytes(content)


def test_corrupt_object_or_metadata_is_rejected() -> None:
    client = FakeS3()
    artifact_store = store(client)
    content = b"correct"
    content_digest = digest(content)
    key = f"team-a/artifacts/sha256/{content_digest[:2]}/{content_digest}"
    client.objects[key] = (content, {"sha256": "b" * 64})

    with pytest.raises(ArtifactIntegrityError, match="metadata digest"):
        artifact_store.get_bytes(content_digest)


@pytest.mark.parametrize(
    ("bucket", "prefix"),
    [("", "safe"), ("A" * 64, "safe"), ("arena-artifacts", ""), ("arena-artifacts", "x" * 513), ("arena-artifacts", "../escape"), ("arena-artifacts", "safe/../../escape"), ("arena-artifacts", "safe/\x00bad")],
)
def test_bucket_and_prefix_reject_traversal_and_unbounded_values(bucket: str, prefix: str) -> None:
    with pytest.raises(ValueError):
        S3CompatibleArtifactStore(bucket, endpoint_url="https://objects.example.test", region_name="us-test-1", prefix=prefix, client=FakeS3())


@pytest.mark.parametrize("endpoint", ["http://objects.example.test", "ftp://objects.example.test", "https://key:secret@objects.example.test", "https://objects.example.test?token=secret"])
def test_endpoint_policy_rejects_insecure_or_credential_bearing_endpoints(endpoint: str) -> None:
    with pytest.raises(ValueError):
        S3CompatibleArtifactStore("arena-artifacts", endpoint_url=endpoint, region_name="us-test-1", prefix="safe", client=FakeS3())


@pytest.mark.parametrize("endpoint", ["http://127.0.0.1:9000", "http://localhost:9000", "http://[::1]:9000", "https://objects.example.test"])
def test_endpoint_policy_allows_tls_and_literal_loopback(endpoint: str) -> None:
    assert S3CompatibleArtifactStore("arena-artifacts", endpoint_url=endpoint, region_name="us-test-1", prefix="safe", client=FakeS3()).endpoint_url == endpoint


def test_byte_limit_rejects_put_and_declared_oversized_get_without_reading() -> None:
    client = FakeS3()
    artifact_store = store(client, max_artifact_bytes=4)
    with pytest.raises(ArtifactIntegrityError, match="byte limit"):
        artifact_store.put_bytes(b"12345")
    assert client.put_calls == []

    claimed = digest(b"12345")
    key = f"team-a/artifacts/sha256/{claimed[:2]}/{claimed}"
    client.objects[key] = (b"12345", {"sha256": claimed})
    with pytest.raises(ArtifactIntegrityError, match="byte limit"):
        artifact_store.get_bytes(claimed)
    assert client.get_bodies[-1].read_sizes == []
    assert client.get_bodies[-1].closed


def test_transport_errors_are_redacted_and_factory_is_lazy() -> None:
    client = FakeS3()
    factory_calls: list[dict[str, Any]] = []

    def factory(**kwargs: Any) -> FakeS3:
        factory_calls.append(kwargs)
        return client

    artifact_store = S3CompatibleArtifactStore(
        "arena-artifacts",
        endpoint_url="https://objects.example.test",
        region_name="us-test-1",
        prefix="safe",
        client_factory=factory,
        path_style=True,
    )
    assert factory_calls == []
    client.put_failure = RuntimeError("request to https://key:secret@objects.example.test/request-123 failed")

    with pytest.raises(ArtifactIntegrityError) as failure:
        artifact_store.put_bytes(b"safe")

    assert "secret" not in str(failure.value)
    assert "objects.example" not in str(failure.value)
    assert factory_calls == [{"endpoint_url": "https://objects.example.test", "region_name": "us-test-1", "path_style": True}]


def test_partial_upload_failure_is_not_accepted_even_if_object_was_written() -> None:
    client = FakeS3()
    client.store_before_failure = True
    client.put_failure = RuntimeError("connection reset after bytes were sent")
    artifact_store = store(client)

    with pytest.raises(ArtifactIntegrityError, match="upload failed"):
        artifact_store.put_bytes(b"partial")

    assert client.objects
