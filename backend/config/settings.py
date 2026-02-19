from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    app_env: str = "dev"
    cors_origins: str = "http://localhost:5173"
    default_main_model_id: str = "claude-sonnet-4-6"
    default_cheap_model_id: str = "claude-haiku-4-5"
    enable_llm_judge: bool = True
    enable_pdf_export: bool = False
    max_concurrent_llm_calls: int = 3

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
