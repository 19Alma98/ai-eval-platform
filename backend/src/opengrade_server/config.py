from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SQLITE_URL = "sqlite+aiosqlite:///./aiobs.db"
DEFAULT_JUDGE_PROMPT_SNAPSHOTS = ".aiobs/judge_prompt_snapshots.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # Local default matches SQLite; Compose / .env override to Postgres.
    database_url: str = DEFAULT_SQLITE_URL
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    project_name_max_length: int = 200
    project_slug_max_length: int = 200
    content_capture_enabled: bool = False
    otlp_max_body_bytes: int = 4 * 1024 * 1024
    json_max_body_bytes: int = 4 * 1024 * 1024
    trace_scores_max_body_bytes: int = 1024 * 1024
    llm_model: str = "gemini/gemini-3.8-flash"
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_max_concurrency: int = 8
    llm_temperature: float = 0.0
    llm_seed: int | None = 42
    judge_prompt_snapshots: str = Field(
        default=DEFAULT_JUDGE_PROMPT_SNAPSHOTS,
        validation_alias=AliasChoices("AIOBS_JUDGE_PROMPT_SNAPSHOTS", "judge_prompt_snapshots"),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
