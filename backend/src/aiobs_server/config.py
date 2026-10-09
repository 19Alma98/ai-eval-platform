from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SQLITE_URL = "sqlite+aiosqlite:///./aiobs.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Local default matches SQLite; Compose / .env override to Postgres.
    database_url: str = DEFAULT_SQLITE_URL
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
    llm_temperature: float = 0.0
    llm_seed: int | None = 42


@lru_cache
def get_settings() -> Settings:
    return Settings()
