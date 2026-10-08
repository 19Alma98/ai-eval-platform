from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class EvaluationSample:
    input: Any
    expected_output: Any | None
    actual_output: Any | None
    context: Any | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    score: float | None
    label: str | None
    explanation: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


class Evaluator(Protocol):
    name: str

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult: ...


class LlmClient(Protocol):
    async def complete(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Run one JSON-mode chat completion and return the raw message text.

        ``history`` is appended after the user message (used for repair retries).
        Parsing and validation are the caller's job.
        """
        ...

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
    ) -> dict[str, Any]: ...
