from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://aiobs:aiobs@localhost:5434/aiobs"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    project_name_max_length: int = 200
    project_slug_max_length: int = 200
    content_capture_enabled: bool = False
    otlp_max_body_bytes: int = 4 * 1024 * 1024
    llm_model: str = "anthropic/claude-sonnet-5"
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_max_concurrency: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
