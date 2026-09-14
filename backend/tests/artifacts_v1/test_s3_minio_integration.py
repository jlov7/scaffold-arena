from __future__ import annotations

import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from artifacts_v1 import ArtifactIntegrityError, S3CompatibleArtifactStore

pytestmark = pytest.mark.integration


def _settings() -> tuple[str, str, str]:
    endpoint = os.environ.get("TEST_S3_ENDPOINT_URL", "").strip()
    bucket = os.environ.get("TEST_S3_BUCKET", "").strip()
    region = os.environ.get("TEST_S3_REGION", "us-east-1").strip()
    if not endpoint or not bucket:
        pytest.skip(
            "TEST_S3_ENDPOINT_URL and TEST_S3_BUCKET are required; "
            "run scripts/test-production-integrations.sh"
        )
    return endpoint, bucket, region


@pytest.fixture(scope="session")
def real_s3_client():
    endpoint, bucket, region = _settings()
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import ClientError
    except ImportError:
        pytest.skip("the team optional dependency is required")

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        config=Config(
            s3={"addressing_style": "path"},
            retries={"max_attempts": 2, "mode": "standard"},
            connect_timeout=2,
            read_timeout=5,
        ),
    )
    try:
        client.create_bucket(Bucket=bucket)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {
            "BucketAlreadyExists",
            "BucketAlreadyOwnedByYou",
            "409",
        }:
            raise
    client.head_bucket(Bucket=bucket)
    return client


def _store(real_s3_client, *, maximum: int = 2 * 1024 * 1024) -> S3CompatibleArtifactStore:
    endpoint, bucket, region = _settings()
    return S3CompatibleArtifactStore(
        bucket,
        endpoint_url=endpoint,
        region_name=region,
        prefix=f"ci/{uuid.uuid4().hex}",
        path_style=True,
        max_artifact_bytes=maximum,
        client=real_s3_client,
    )


def test_real_s3_conditional_writes_are_content_addressed_and_concurrent(real_s3_client) -> None:
    store = _store(real_s3_client)
    content = (b"scaffold-arena-real-s3-integration\n" * 4096) + b"terminal"

    with ThreadPoolExecutor(max_workers=8) as workers:
        digests = tuple(
            workers.map(
                lambda _: store.put_bytes(
                    content,
                    media_type="application/vnd.scaffold-arena.integration+octets",
                ),
                range(16),
            )
        )

    assert len(set(digests)) == 1
    digest = digests[0]
    assert store.get_bytes(digest) == content
    assert store.uri_for(digest) == f"s3://{store.bucket}/{store._key(digest)}"

    head = real_s3_client.head_object(Bucket=store.bucket, Key=store._key(digest))
    assert head["ContentLength"] == len(content)
    assert head["Metadata"]["sha256"] == digest
    assert head["ContentType"] == "application/vnd.scaffold-arena.integration+octets"


def test_real_s3_missing_and_tampered_objects_fail_closed(real_s3_client) -> None:
    store = _store(real_s3_client)
    missing = "f" * 64
    with pytest.raises(FileNotFoundError):
        store.get_bytes(missing)

    claimed_content = b"claimed content"
    claimed_digest = hashlib.sha256(claimed_content).hexdigest()
    real_s3_client.put_object(
        Bucket=store.bucket,
        Key=store._key(claimed_digest),
        Body=b"different content",
        ContentType="application/octet-stream",
        Metadata={"sha256": claimed_digest},
    )
    with pytest.raises(ArtifactIntegrityError, match="content does not match"):
        store.get_bytes(claimed_digest)

    metadata_content = b"metadata mismatch"
    metadata_digest = hashlib.sha256(metadata_content).hexdigest()
    real_s3_client.put_object(
        Bucket=store.bucket,
        Key=store._key(metadata_digest),
        Body=metadata_content,
        ContentType="application/octet-stream",
        Metadata={"sha256": "0" * 64},
    )
    with pytest.raises(ArtifactIntegrityError, match="metadata digest"):
        store.get_bytes(metadata_digest)


def test_real_s3_enforces_put_and_read_byte_limits(real_s3_client) -> None:
    store = _store(real_s3_client, maximum=32)
    with pytest.raises(ArtifactIntegrityError, match="byte limit"):
        store.put_bytes(b"x" * 33)

    oversized = b"y" * 33
    digest = hashlib.sha256(oversized).hexdigest()
    real_s3_client.put_object(
        Bucket=store.bucket,
        Key=store._key(digest),
        Body=oversized,
        ContentType="application/octet-stream",
        Metadata={"sha256": digest},
    )
    with pytest.raises(ArtifactIntegrityError, match="byte limit"):
        store.get_bytes(digest)
