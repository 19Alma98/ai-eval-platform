"""Settings shared by the tour scripts, read from environment variables.

A ``.env`` file next to ``pyproject.toml`` is loaded first (see ``.env.example``);
variables already set in the shell win over the file.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def _load_dotenv(path: Path) -> None:
    """Minimal ``.env`` loader (KEY=VALUE lines) so the tour needs no extra dependency."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

# Where the OpenGrade platform runs (API + UI + OTLP endpoint at <uri>/v1/traces).
TRACKING_URI = os.getenv("OPENGRADE_TRACKING_URI", "http://localhost:8000")
# Project that receives traces, datasets and experiments (created if missing).
PROJECT = os.getenv("OPENGRADE_PROJECT", "nimbus-support")

# Models to use. Names starting with "fake-" run offline (deterministic, no LLM needed);
# any other name is sent to an OpenAI-compatible endpoint (Ollama, OpenAI, vLLM, ...).
DEFAULT_MODEL = os.getenv("TOUR_MODEL", "fake-large")
COMPARE_MODELS = [
    m.strip() for m in os.getenv("TOUR_COMPARE_MODELS", "fake-small,fake-large").split(",") if m
]
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")  # Ollama by default
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")

# "1" when the platform has an LLM judge configured (LLM_MODEL / LLM_API_KEY on the
# server): the scripts then also use groundedness, correctness and custom LLM judges.
USE_LLM_JUDGES = os.getenv("TOUR_LLM_JUDGES", "0").lower() in {"1", "true", "yes", "on"}

# Release / deployment tags for production traffic (Production -> Health in the UI).
APP_VERSION = os.getenv("TOUR_APP_VERSION", "1.4.0")
APP_ENVIRONMENT = os.getenv("TOUR_APP_ENVIRONMENT", "dev")

# Optional webhook (Slack incoming webhook or any URL) for the alerts of script 04.
ALERT_WEBHOOK_URL = os.getenv("TOUR_ALERT_WEBHOOK_URL") or None
