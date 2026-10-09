from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

_STEP_RE = re.compile(r"^STEP: (\S+)", re.MULTILINE)
_CLAIM_LINE_RE = re.compile(r"^\[C\d+\] ", re.MULTILINE)
_DOC_LINE_RE = re.compile(r"^\[D\d+\] ", re.MULTILINE)

Reply = str | dict[str, Any] | Callable[[str], "str | dict[str, Any]"] | BaseException


def step_of(system: str) -> str:
    match = _STEP_RE.search(system)
    return match.group(1) if match else ""


def claim_count(user: str) -> int:
    return len(_CLAIM_LINE_RE.findall(user))


def doc_count(user: str) -> int:
    return len(_DOC_LINE_RE.findall(user))


def default_reply(step: str, user: str) -> dict[str, Any]:
    """A reply that makes every claim pass and every rubric score the top level."""
    if step.startswith("extract"):
        return {"claims": ["The answer states a fact."]}
    if step in ("verify_reference_coverage", "verify_context_coverage"):
        return {"verdicts": [{"reasoning": "ok", "verdict": "covered"}] * claim_count(user)}
    if step == "verify_context_relevance":
        return {"verdicts": [{"reasoning": "ok", "verdict": "relevant"}] * doc_count(user)}
    if step.startswith("verify"):
        return {
            "verdicts": [{"reasoning": "ok", "verdict": "supported", "doc_ids": [], "quote": None}]
            * claim_count(user)
        }
    if step.startswith("rubric"):
        return {"reasoning": "ok", "level": 5}
    raise AssertionError(f"unexpected judge step: {step!r}")


class ScriptedJudgeLlm:
    """Fake LlmClient for judge tests.

    Replies are chosen by the ``STEP:`` tag on the first line of the system prompt.
    A list is consumed in order (its last reply repeats); a callable receives the
    user prompt; an exception instance is raised. Steps without a script get
    ``default_reply``.
    """

    def __init__(self, script: dict[str, Reply | list[Reply]] | None = None) -> None:
        self._script = {
            step: list(reply) if isinstance(reply, list) else [reply]
            for step, reply in (script or {}).items()
        }
        self.calls: list[dict[str, Any]] = []

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
        step = step_of(system)
        self.calls.append(
            {
                "step": step,
                "system": system,
                "user": user,
                "model": model,
                "temperature": temperature,
                "seed": seed,
                "history": history,
            }
        )
        replies = self._script.get(step)
        if replies:
            reply: Reply = replies.pop(0) if len(replies) > 1 else replies[0]
        else:
            reply = default_reply(step, user)
        if isinstance(reply, BaseException):
            raise reply
        if callable(reply):
            reply = reply(user)
        return reply if isinstance(reply, str) else json.dumps(reply)

    def steps(self) -> list[str]:
        return [call["step"] for call in self.calls]
