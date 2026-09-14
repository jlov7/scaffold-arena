from __future__ import annotations

import hashlib
import io
import json
from typing import Any

import pytest

from artifacts_v1 import LocalArtifactStore, S3CompatibleArtifactStore
from config.settings import Settings
from services_v1.runtime import (
    ProtocolRuntimeConfigurationError,
    _build_artifact_store,
    _validate_local_configuration,
    _verify_team_artifact_connectivity,
    initialize_durable_worker_runtime,
)


def team_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "protocol_v1_deployment_profile": "team",
        "protocol_v1_database_url": "postgresql://arena.example.test/arena",
        "protocol_v1_oidc_issuer": "https://issuer.example.test",
        "protocol_v1_oidc_client_id": "arena-client",
        "protocol_v1_oidc_redirect_uri": "https://arena.example.test/api/v1/callback",
        "protocol_v1_oidc_allowed_redirect_uris": "https://arena.example.test/api/v1/callback",
        "protocol_v1_session_secret": "x" * 32,
        "protocol_v1_session_cookie_secure": True,
        "protocol_v1_artifact_backend": "s3_compatible",
        "protocol_v1_s3_bucket": "arena-artifacts",
        "protocol_v1_s3_endpoint_url": "https://objects.example.test",
        "protocol_v1_s3_region_name": "us-test-1",
        "protocol_v1_s3_prefix": "team-a/artifacts",
    }
    values.update(overrides)
    return Settings(**values)


def test_team_artifact_configuration_fails_closed_when_s3_is_incomplete() -> None:
    with pytest.raises(RuntimeError, match="team deployment requires protocol_v1_artifact_backend"):
        team_settings(protocol_v1_artifact_backend="local").validate_protocol_v1_team_configuration()
    with pytest.raises(RuntimeError, match="protocol_v1_s3_prefix"):
        team_settings(protocol_v1_s3_prefix="").validate_protocol_v1_team_configuration()
    with pytest.raises(RuntimeError, match="maximum bytes"):
        team_settings(protocol_v1_s3_max_artifact_bytes=0).validate_protocol_v1_team_configuration()


def test_team_development_local_override_remains_readiness_hold(tmp_path) -> None:
    settings = team_settings(
        protocol_v1_artifact_backend="local",
        protocol_v1_team_allow_local_artifacts_development=True,
        protocol_v1_artifact_root=str(tmp_path / "artifacts"),
    )

    database_url, root = _validate_local_configuration(settings)

    assert database_url.startswith("postgresql://")
    assert root == tmp_path / "artifacts"
    assert settings.protocol_v1_team_artifact_readiness == "HOLD_DEVELOPMENT_LOCAL_ARTIFACTS"
    assert isinstance(_build_artifact_store(settings, root, s3_client=None, s3_client_factory=None), LocalArtifactStore)


def test_runtime_builds_lazy_s3_store_with_injected_fake_client() -> None:
    client = object()
    settings = team_settings(protocol_v1_s3_path_style=True)

    artifact_store = _build_artifact_store(settings, None, s3_client=client, s3_client_factory=None)

    assert isinstance(artifact_store, S3CompatibleArtifactStore)
    assert artifact_store._s3 is client
    assert artifact_store.endpoint_url == "https://objects.example.test"
    assert artifact_store.path_style is True


def test_runtime_rejects_missing_local_root() -> None:
    with pytest.raises(ProtocolRuntimeConfigurationError, match="artifact_root"):
        _build_artifact_store(Settings(), None, s3_client=None, s3_client_factory=None)


def test_team_artifact_readiness_uses_a_fixed_content_addressed_sentinel() -> None:
    class ProbeStore:
        def __init__(self) -> None:
            self.content = b""
            self.digest = ""

        def put_bytes(self, content: bytes, **_kwargs: Any) -> str:
            self.content = content
            self.digest = hashlib.sha256(content).hexdigest()
            return self.digest

        def get_bytes(self, digest: str) -> bytes:
            assert digest == self.digest
            return self.content

        def uri_for(self, digest: str) -> str:
            return digest

    store = ProbeStore()
    _verify_team_artifact_connectivity(store)
    assert store.content == b"scaffold-arena-artifact-readiness-v1\n"


def test_team_artifact_readiness_failure_blocks_startup() -> None:
    class FailingStore:
        def put_bytes(self, _content: bytes, **_kwargs: Any) -> str:
            raise RuntimeError("transport credential=secret endpoint=https://objects.example.test")

        def get_bytes(self, _digest: str) -> bytes:
            return b""

        def uri_for(self, digest: str) -> str:
            return digest

    with pytest.raises(ProtocolRuntimeConfigurationError, match="readiness probe failed") as failure:
        _verify_team_artifact_connectivity(FailingStore())
    assert "secret" not in str(failure.value)


@pytest.mark.asyncio
async def test_team_worker_probes_the_same_s3_sentinel_before_it_can_lease(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeS3:
        def __init__(self) -> None:
            self.objects: dict[str, tuple[bytes, dict[str, str]]] = {}
            self.put_calls: list[dict[str, Any]] = []

        def put_object(self, **kwargs: Any) -> None:
            self.put_calls.append(kwargs)
            self.objects[str(kwargs["Key"])] = (
                bytes(kwargs["Body"]),
                dict(kwargs["Metadata"]),
            )

        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
            del Bucket
            content, metadata = self.objects[Key]
            return {
                "Body": io.BytesIO(content),
                "ContentLength": len(content),
                "Metadata": metadata,
            }

    config = tmp_path / "adapter-runtime.json"
    config.write_text(json.dumps({
        "format": "scaffold-arena-adapter-runtime-v1",
        "adapters": [{"kind": "bundled_offline_demo_fixture"}],
    }))
    database = tmp_path / "team-worker.db"
    client = FakeS3()
    settings = team_settings(protocol_v1_adapter_runtime_config=str(config))

    # The production path requires PostgreSQL. This test substitutes local
    # persistence only to prove the S3/worker composition without a network.
    monkeypatch.setattr(
        "services_v1.runtime._validate_worker_configuration",
        lambda _settings: (f"sqlite:///{database}", None),
    )

    runtime = await initialize_durable_worker_runtime(settings, s3_client=client)
    try:
        assert isinstance(runtime.artifact_store, S3CompatibleArtifactStore)
        assert runtime.artifact_connectivity_verified is True
        assert client.put_calls[0]["Body"] == b"scaffold-arena-artifact-readiness-v1\n"
        assert runtime.worker.artifact_store is runtime.artifact_store
        assert runtime.evaluator.service.artifact_store is runtime.artifact_store
    finally:
        runtime.close()
