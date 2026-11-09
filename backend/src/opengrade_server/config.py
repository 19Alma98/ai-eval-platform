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
    content_capture_enabled: bool = True
    otlp_max_body_bytes: int = 4 * 1024 * 1024
    otlp_trace_sample_rate: float = 1.0
    otlp_max_span_attr_chars: int = 32768
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
    forwarded_allow_ips: str = "*"
    shutdown_grace_seconds: int = 30
    # OTLP ingest backpressure (per process; assume single API replica)
    otlp_rate_limit_per_second: float = 50.0
    otlp_max_inflight: int = 32
    otlp_max_pending_scores: int = 200
    otlp_retry_after_seconds: int = 1
    # Server-side alerts: rules are evaluated in the API process every interval.
    alerts_enabled: bool = True
    alerts_interval_seconds: float = 60.0
    # Webhook for rules without their own (Slack/Teams/any JSON endpoint).
    alert_webhook_url: str | None = None
    alert_webhook_timeout_seconds: float = 10.0
    # Where the UI is reachable from outside, for links in alert notifications.
    public_base_url: str | None = None
    # Production data retention: default days for projects without their own setting
    # (unset = keep forever) and how often the purge runs.
    retention_days: int | None = Field(default=None, ge=1)
    retention_interval_hours: float = 24.0
    # API key auth. Unset = no auth (localhost / trusted network). Set = every /api and
    # OTLP request needs ``Authorization: Bearer <key>`` or a UI session cookie.
    api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("OPENGRADE_API_KEY", "api_key")
    )
    ui_session_hours: float = Field(
        default=12.0,
        gt=0,
        validation_alias=AliasChoices("OPENGRADE_UI_SESSION_HOURS", "ui_session_hours"),
    )
    auth_failed_attempts_per_minute: int = Field(
        default=60,
        ge=0,
        validation_alias=AliasChoices(
            "OPENGRADE_AUTH_FAILED_ATTEMPTS_PER_MINUTE", "auth_failed_attempts_per_minute"
        ),
    )
    auth_failed_lockout_seconds: int = Field(
        default=60,
        ge=1,
        validation_alias=AliasChoices(
            "OPENGRADE_AUTH_FAILED_LOCKOUT_SECONDS", "auth_failed_lockout_seconds"
        ),
    )

    def accepted_api_keys(self) -> tuple[str, ...]:
        key = (self.api_key or "").strip()
        return (key,) if key else ()


@lru_cache
def get_settings() -> Settings:
    return Settings()
