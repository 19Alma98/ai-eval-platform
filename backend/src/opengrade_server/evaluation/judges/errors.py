from __future__ import annotations

JUDGE_OUTPUT_INVALID = "judge_output_invalid"
LLM_UNAVAILABLE = "llm_unavailable"
CONTEXT_OVERFLOW = "context_overflow"
LLM_ERROR = "llm_error"
LLM_NOT_CONFIGURED = "llm_not_configured"

JUDGE_NOT_CONFIGURED_MSG = "judge not configured: set LLM_MODEL and LLM_API_KEY"


class JudgeOutputError(Exception):
    """The judge model's reply could not be used, even after one format repair."""

    def __init__(self, message: str, *, raw: str) -> None:
        super().__init__(message)
        self.raw = raw


class JudgeNotConfiguredError(RuntimeError):
    """Judge model/key is missing; do not call the provider."""

    def __init__(self, message: str = JUDGE_NOT_CONFIGURED_MSG) -> None:
        super().__init__(message)


def judge_needs_api_key(model: str, api_base: str | None) -> bool:
    """Same rule as the ``opengrade ui`` startup warning for missing ``LLM_API_KEY``."""
    if model.startswith("gemini/"):
        return True
    if model.startswith("ollama/"):
        return False
    if api_base:
        return False
    return True


def _is_auth_error(exc: BaseException) -> bool:
    from litellm import exceptions as llm_exc

    return isinstance(exc, llm_exc.AuthenticationError)


def classify_llm_error(exc: BaseException) -> str:
    """Map a provider exception to a stable ``metadata.error_type``."""
    from litellm import exceptions as llm_exc

    if isinstance(exc, JudgeNotConfiguredError) or _is_auth_error(exc):
        return LLM_NOT_CONFIGURED
    if isinstance(exc, llm_exc.ContextWindowExceededError):
        return CONTEXT_OVERFLOW
    if isinstance(
        exc,
        (
            TimeoutError,
            llm_exc.Timeout,
            llm_exc.APIConnectionError,
            llm_exc.RateLimitError,
            llm_exc.ServiceUnavailableError,
            llm_exc.InternalServerError,
        ),
    ):
        return LLM_UNAVAILABLE
    return LLM_ERROR


def explain_llm_error(exc: BaseException) -> str:
    """One-line explanation for ERROR results (never dump a LiteLLM traceback)."""
    if isinstance(exc, JudgeNotConfiguredError) or _is_auth_error(exc):
        return JUDGE_NOT_CONFIGURED_MSG
    return f"{type(exc).__name__}: {exc}"[:2000]
