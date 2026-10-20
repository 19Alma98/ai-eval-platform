from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SQLITE_URL = "sqlite+aiosqlite:///./opengrade.db"
DEFAULT_JUDGE_PROMPT_SNAPSHOTS = ".opengrade/judge_prompt_snapshots.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # Local default matches SQLite; Compose / .env override to Postgres.
    database_url: str = DEFAULT_SQLITE_URL
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    project_name_max_length: int = 200
    project_slug_max_length: int = 200
    # Store span text (inputs/outputs, prompts, completions). Live scoring and the
    # RAG view need it; set CONTENT_CAPTURE_ENABLED=false to redact at ingestion.
    content_capture_enabled: bool = True
    otlp_max_body_bytes: int = 4 * 1024 * 1024
    json_max_body_bytes: int = 4 * 1024 * 1024
    dataset_import_max_bytes: int = 4 * 1024 * 1024
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
        validation_alias=AliasChoices("OPENGRADE_JUDGE_PROMPT_SNAPSHOTS", "judge_prompt_snapshots"),
    )
    # Container / reverse-proxy (uvicorn entrypoint also reads env directly)
    forwarded_allow_ips: str = "*"
    shutdown_grace_seconds: int = 30
    # OTLP ingest backpressure (per process; assume single API replica)
    otlp_rate_limit_per_second: float = 50.0
    otlp_max_inflight: int = 32
    otlp_max_pending_scores: int = 200
    otlp_retry_after_seconds: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()
