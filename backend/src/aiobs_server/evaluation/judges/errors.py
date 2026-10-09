from __future__ import annotations

JUDGE_OUTPUT_INVALID = "judge_output_invalid"
LLM_UNAVAILABLE = "llm_unavailable"
CONTEXT_OVERFLOW = "context_overflow"
LLM_ERROR = "llm_error"


class JudgeOutputError(Exception):
    """The judge model's reply could not be used, even after one repair retry."""

    def __init__(self, message: str, *, raw: str) -> None:
        super().__init__(message)
        self.raw = raw


def classify_llm_error(exc: BaseException) -> str:
    """Map a provider exception to a stable ``metadata.error_type``."""
    from litellm import exceptions as llm_exc

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
