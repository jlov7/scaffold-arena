from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_team_compose_uses_fixed_settings_owned_worker_and_healthchecks() -> None:
    compose = (ROOT / "deploy" / "compose.team.yml").read_text()

    assert "${POSTGRES_PASSWORD:?" in compose
    assert "${PROTOCOL_V1_SESSION_SECRET:?" in compose
    assert "PROTOCOL_V1_ARTIFACT_BACKEND: s3_compatible" in compose
    assert "condition: service_healthy" in compose
    assert "object-store:" not in compose
    assert "MINIO_ROOT_" not in compose
    assert "WORKER_RUNTIME_COMMAND" not in compose
    assert "  worker:" in compose
    assert 'command: ["uv", "run", "arena", "worker"]' in compose
    assert 'test: ["CMD", "uv", "run", "arena", "worker", "--healthcheck"]' in compose
    assert "PROTOCOL_V1_ADAPTER_RUNTIME_CONFIG: /etc/scaffold-arena/adapter-runtime.json" in compose
    assert "POSTGRES_PASSWORD: arena" not in compose
    assert "MINIO_ROOT_PASSWORD: arena" not in compose


def test_backup_and_restore_default_to_dry_run_without_printing_database_url() -> None:
    environment = {key: value for key, value in os.environ.items() if key != "PROTOCOL_V1_DATABASE_URL"}
    backup = subprocess.run(["bash", str(ROOT / "scripts/deployment/backup-postgres.sh")], env=environment, capture_output=True, text=True, check=True)
    restore = subprocess.run(["bash", str(ROOT / "scripts/deployment/restore-postgres.sh"), "--input", "backup.dump"], env=environment, capture_output=True, text=True, check=True)

    assert "DRY_RUN" in backup.stdout
    assert "DRY_RUN" in restore.stdout
    assert "secret" not in backup.stdout + backup.stderr + restore.stdout + restore.stderr


def test_production_images_use_pinned_uv_copy_and_nonroot_runtime() -> None:
    for path in (ROOT / "backend" / "Dockerfile", ROOT / "Dockerfile"):
        dockerfile = path.read_text()
        assert "ghcr.io/astral-sh/uv:0.6.14" in dockerfile
        assert "COPY --from=uv /uv /uvx /bin/" in dockerfile
        assert "pip install" not in dockerfile
        assert "USER arena" in dockerfile
        assert "--no-install-project" in dockerfile
        assert dockerfile.index("--no-install-project") < dockerfile.rindex("RUN uv sync")

    assert 'uv run arena serve --host 0.0.0.0' in (ROOT / "Dockerfile").read_text()
    assert '"arena", "serve", "--host", "0.0.0.0"' in (
        ROOT / "backend" / "Dockerfile"
    ).read_text()

    development_compose = (ROOT / "docker-compose.yml").read_text()
    assert '"127.0.0.1:8000:8000"' in development_compose
    assert '"127.0.0.1:5173:5173"' in development_compose

    root_ignore = (ROOT / ".dockerignore").read_text()
    for pattern in (
        "**/.venv",
        "**/data",
        "**/build",
        "**/*.egg-info",
        ".codex/",
        ".agents/",
        ".cursor/",
    ):
        assert pattern in root_ignore
