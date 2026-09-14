from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import inspect, select

from artifacts_v1 import S3CompatibleArtifactStore
from config.settings import Settings
from persistence_v1.schema import projects
from services_v1.runtime import (
    initialize_durable_worker_runtime,
    initialize_protocol_registry,
)

pytestmark = pytest.mark.integration


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(
            f"{name} is required; run scripts/test-production-integrations.sh"
        )
    return value


def _team_settings(*, prefix: str, adapter_config: str = "", project_id: str = "") -> Settings:
    database_url = _required("TEST_POSTGRES_URL")
    endpoint = _required("TEST_S3_ENDPOINT_URL")
    bucket = _required("TEST_S3_BUCKET")
    region = os.environ.get("TEST_S3_REGION", "us-east-1")
    redirect = "https://arena.integration.test/api/v1/callback"
    return Settings(
        protocol_v1_deployment_profile="team",
        protocol_v1_database_url=database_url,
        protocol_v1_artifact_backend="s3_compatible",
        protocol_v1_s3_bucket=bucket,
        protocol_v1_s3_endpoint_url=endpoint,
        protocol_v1_s3_region_name=region,
        protocol_v1_s3_prefix=prefix,
        protocol_v1_s3_path_style=True,
        protocol_v1_s3_max_artifact_bytes=2 * 1024 * 1024,
        protocol_v1_oidc_issuer="https://issuer.integration.test",
        protocol_v1_oidc_client_id="arena-integration-client",
        protocol_v1_oidc_redirect_uri=redirect,
        protocol_v1_oidc_allowed_redirect_uris=redirect,
        protocol_v1_session_secret="integration-session-secret-" + "x" * 32,
        protocol_v1_session_cookie_secure=True,
        protocol_v1_adapter_runtime_config=adapter_config,
        protocol_v1_worker_project_id=project_id,
        protocol_v1_worker_owner="integration-worker",
    )


@pytest.mark.asyncio
async def test_real_team_registry_migrates_postgres_and_probes_object_storage() -> None:
    prefix = f"runtime/{uuid.uuid4().hex}"
    runtime = await initialize_protocol_registry(_team_settings(prefix=prefix))
    try:
        assert runtime.engine.dialect.name == "postgresql"
        assert isinstance(runtime.artifact_store, S3CompatibleArtifactStore)
        assert runtime.artifact_connectivity_verified is True
        assert runtime.auth_service is not None
        assert "alembic_version" in inspect(runtime.engine).get_table_names()

        project_id = f"integration-{uuid.uuid4().hex}"
        assert runtime.service.repository.create_project(
            "Production integration",
            project_id=project_id,
        ) == project_id
        with runtime.engine.connect() as connection:
            assert connection.execute(
                select(projects.c.id).where(projects.c.id == project_id)
            ).scalar_one() == project_id

        content = b"team-runtime-real-object-storage\n"
        digest = runtime.artifact_store.put_bytes(content)
        assert runtime.artifact_store.get_bytes(digest) == content
    finally:
        runtime.close()


@pytest.mark.asyncio
async def test_real_team_worker_starts_only_after_postgres_and_s3_are_ready(tmp_path) -> None:
    project_id = f"worker-{uuid.uuid4().hex}"
    prefix = f"worker/{uuid.uuid4().hex}"
    registry = await initialize_protocol_registry(_team_settings(prefix=prefix))
    try:
        registry.service.repository.create_project(
            "Worker integration",
            project_id=project_id,
        )
    finally:
        registry.close()

    adapter_config = tmp_path / "adapter-runtime.json"
    adapter_config.write_text(
        json.dumps(
            {
                "format": "scaffold-arena-adapter-runtime-v1",
                "adapters": [{"kind": "bundled_offline_demo_fixture"}],
            }
        ),
        encoding="utf-8",
    )
    worker = await initialize_durable_worker_runtime(
        _team_settings(
            prefix=prefix,
            adapter_config=str(adapter_config),
            project_id=project_id,
        )
    )
    try:
        assert worker.engine.dialect.name == "postgresql"
        assert worker.project_id == project_id
        assert worker.artifact_connectivity_verified is True
        assert worker.worker.artifact_store is worker.artifact_store
        assert worker.evaluator.service.artifact_store is worker.artifact_store
    finally:
        worker.close()
