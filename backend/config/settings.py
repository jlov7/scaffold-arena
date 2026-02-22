from __future__ import annotations

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
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
