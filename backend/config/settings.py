from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    openrouter_api_key: str = ""
    gemini_openai_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = ""
    openrouter_app_name: str = "Scaffold Arena"
    app_env: str = "dev"
    cors_origins: str = "http://localhost:5173"
    api_secret_key: str = ""
    default_main_model_id: str = "claude-sonnet-4-6"
    default_cheap_model_id: str = "claude-haiku-4-5"
    enable_llm_judge: bool = True
    enable_pdf_export: bool = False
    max_concurrent_llm_calls: int = 3
    max_cost_per_run_usd: float = 2.0
    daily_budget_usd: float = 50.0
    max_request_size_bytes: int = 1_000_000
    run_ttl_seconds: int = 1800
    provider_max_retries: int = 3
    provider_retry_base_delay_ms: int = 250
    sqlite_path: str = "data/scaffold_arena.db"
    protocol_v1_database_url: str = ""
    protocol_v1_artifact_root: str = ""
    protocol_v1_artifact_backend: Literal["local", "s3_compatible"] = "local"
    # This narrowly permits a team-profile development environment to exercise
    # auth/RBAC without object storage. It is intentionally a readiness HOLD.
    protocol_v1_team_allow_local_artifacts_development: bool = False
    protocol_v1_s3_bucket: str = ""
    protocol_v1_s3_endpoint_url: str = ""
    protocol_v1_s3_region_name: str = ""
    protocol_v1_s3_prefix: str = ""
    protocol_v1_s3_path_style: bool = False
    protocol_v1_s3_max_artifact_bytes: int = 32 * 1024 * 1024
    protocol_v1_personal_project_id: str = "personal"
    protocol_v1_personal_project_name: str = "Personal"
    protocol_v1_adapter_runtime_config: str = ""
    protocol_v1_worker_project_id: str = ""
    protocol_v1_worker_owner: str = "arena-worker"
    protocol_v1_worker_lease_seconds: float = 30.0
    protocol_v1_worker_poll_seconds: float = 0.5
    # Team mode is deliberately opt-in. Personal mode is the local-workbench
    # authority ceiling and never acquires an identity provider dependency.
    protocol_v1_deployment_profile: Literal["personal", "team"] = "personal"
    protocol_v1_oidc_issuer: str = ""
    protocol_v1_oidc_client_id: str = ""
    protocol_v1_oidc_redirect_uri: str = ""
    protocol_v1_oidc_allowed_redirect_uris: str = ""
    protocol_v1_session_secret: str = ""
    protocol_v1_session_cookie_name: str = "__Host-arena-session"
    protocol_v1_session_cookie_secure: bool = False
    protocol_v1_session_cookie_samesite: Literal["lax", "strict"] = "lax"
    protocol_v1_session_ttl_seconds: int = 28_800
    protocol_v1_oidc_transaction_ttl_seconds: int = 600
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def resolved_protocol_v1_database_url(self) -> str:
        if self.protocol_v1_database_url.strip():
            return self.protocol_v1_database_url.strip()
        database_path = Path(self.sqlite_path).with_name(
            f"{Path(self.sqlite_path).stem}_v1{Path(self.sqlite_path).suffix or '.db'}"
        )
        return f"sqlite:///{database_path}"

    @property
    def resolved_protocol_v1_artifact_root(self) -> Path:
        if self.protocol_v1_artifact_root.strip():
            return Path(self.protocol_v1_artifact_root)
        return Path(self.sqlite_path).parent / "artifacts-v1"

    @property
    def protocol_v1_is_team_mode(self) -> bool:
        return self.protocol_v1_deployment_profile == "team"

    @property
    def protocol_v1_team_artifact_readiness(self) -> str:
        if not self.protocol_v1_is_team_mode:
            return "PERSONAL_LOCAL"
        if self.protocol_v1_artifact_backend == "s3_compatible":
            return "CONFIGURED_NOT_PROBED"
        return "HOLD_DEVELOPMENT_LOCAL_ARTIFACTS"

    @property
    def protocol_v1_allowed_redirect_uris(self) -> tuple[str, ...]:
        return tuple(
            item.strip()
            for item in self.protocol_v1_oidc_allowed_redirect_uris.split(",")
            if item.strip()
        )

    @property
    def resolved_protocol_v1_worker_project_id(self) -> str:
        if self.protocol_v1_is_team_mode:
            return self.protocol_v1_worker_project_id.strip()
        return self.protocol_v1_personal_project_id.strip()

    def validate_protocol_v1_team_configuration(self) -> None:
        """Reject partial team configuration before any durable runtime starts."""
        if not self.protocol_v1_is_team_mode:
            return
        database_url = self.protocol_v1_database_url.strip()
        required = {
            "protocol_v1_database_url": database_url,
            "protocol_v1_oidc_issuer": self.protocol_v1_oidc_issuer.strip(),
            "protocol_v1_oidc_client_id": self.protocol_v1_oidc_client_id.strip(),
            "protocol_v1_oidc_redirect_uri": self.protocol_v1_oidc_redirect_uri.strip(),
            "protocol_v1_session_secret": self.protocol_v1_session_secret.strip(),
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise RuntimeError("team deployment configuration missing: " + ", ".join(missing))
        if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise RuntimeError("team deployment requires a PostgreSQL protocol_v1_database_url")
        if not self.protocol_v1_oidc_issuer.startswith("https://"):
            raise RuntimeError("team deployment requires an HTTPS OIDC issuer")
        if not self.protocol_v1_oidc_redirect_uri.startswith("https://"):
            raise RuntimeError("team deployment requires an HTTPS OIDC redirect URI")
        if self.protocol_v1_oidc_redirect_uri not in self.protocol_v1_allowed_redirect_uris:
            raise RuntimeError("team deployment redirect URI must be explicitly allowlisted")
        if len(self.protocol_v1_session_secret.strip()) < 32:
            raise RuntimeError("team deployment session secret must be at least 32 characters")
        if not self.protocol_v1_session_cookie_secure:
            raise RuntimeError("team deployment requires Secure session cookies")
        if not self.protocol_v1_session_cookie_name.startswith("__Host-"):
            raise RuntimeError("team deployment session cookie must use the __Host- prefix")
        if self.protocol_v1_session_ttl_seconds <= 0 or self.protocol_v1_oidc_transaction_ttl_seconds <= 0:
            raise RuntimeError("team deployment session and login transaction TTLs must be positive")
        if self.protocol_v1_artifact_backend == "local":
            if not self.protocol_v1_team_allow_local_artifacts_development:
                raise RuntimeError("team deployment requires protocol_v1_artifact_backend=s3_compatible")
            return
        required_artifacts = {
            "protocol_v1_s3_bucket": self.protocol_v1_s3_bucket.strip(),
            "protocol_v1_s3_endpoint_url": self.protocol_v1_s3_endpoint_url.strip(),
            "protocol_v1_s3_region_name": self.protocol_v1_s3_region_name.strip(),
            "protocol_v1_s3_prefix": self.protocol_v1_s3_prefix.strip(),
        }
        missing_artifacts = sorted(name for name, value in required_artifacts.items() if not value)
        if missing_artifacts:
            raise RuntimeError("team S3 artifact configuration missing: " + ", ".join(missing_artifacts))
        if self.protocol_v1_s3_max_artifact_bytes <= 0:
            raise RuntimeError("team S3 artifact maximum bytes must be positive")

    def validate_protocol_v1_worker_configuration(self) -> None:
        """Validate the fixed, settings-owned durable worker boundary."""
        if self.protocol_v1_is_team_mode:
            self.validate_protocol_v1_team_configuration()
            if self.protocol_v1_artifact_backend != "s3_compatible":
                raise RuntimeError("team worker requires protocol_v1_artifact_backend=s3_compatible")
        elif not self.resolved_protocol_v1_database_url.startswith("sqlite:///"):
            raise RuntimeError("personal worker requires a durable local SQLite database")
        if not self.protocol_v1_adapter_runtime_config.strip():
            raise RuntimeError("worker requires protocol_v1_adapter_runtime_config")
        if not self.resolved_protocol_v1_worker_project_id:
            raise RuntimeError("worker requires a non-empty project scope")
        owner = self.protocol_v1_worker_owner.strip()
        if not re.fullmatch(r"[a-z][a-z0-9._-]{2,50}", owner):
            raise RuntimeError("worker owner must leave room for a unique runtime suffix")
        if not 1.0 <= self.protocol_v1_worker_lease_seconds <= 3600.0:
            raise RuntimeError("worker lease seconds must be between 1 and 3600")
        if not 0.05 <= self.protocol_v1_worker_poll_seconds <= 60.0:
            raise RuntimeError("worker poll seconds must be between 0.05 and 60")


settings = Settings()
