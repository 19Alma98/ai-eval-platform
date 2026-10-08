from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from aiobs.evaluation.judges.errors import JudgeOutputError
from aiobs.evaluation.protocol import LlmClient

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

REPAIR_INSTRUCTION = (
    "Your previous reply could not be used: {error}\n"
    "Reply again with JSON only, following exactly the format in the instructions."
)


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating fences and surrounding prose.

    Small models often wrap JSON in markdown or chatter even in JSON mode.
    Raises ValueError when no JSON object can be recovered.
    """
    stripped = (text or "").strip()
    if not stripped:
        raise ValueError("empty response")
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = _search_fences_then_text(stripped)
    if not isinstance(data, dict):
        raise ValueError("response must be a JSON object")
    return data


def _search_fences_then_text(text: str) -> Any:
    for fenced in _FENCE_RE.finditer(text):
        try:
            return _first_balanced_object(fenced.group(1).strip())
        except ValueError:
            continue
    return _first_balanced_object(text)


def _first_balanced_object(text: str) -> Any:
    start = text.find("{")
    while start != -1:
        end = _matching_brace(text, start)
        if end is not None:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        start = text.find("{", start + 1)
    raise ValueError("no JSON object found in response")


def _matching_brace(text: str, start: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


@dataclass(frozen=True, slots=True)
class CallOptions:
    model: str | None
    temperature: float | None


@dataclass(frozen=True, slots=True)
class StructuredResult[T: BaseModel]:
    value: T
    calls: int


async def call_structured[T: BaseModel](
    llm: LlmClient,
    *,
    system: str,
    user: str,
    schema: type[T],
    options: CallOptions,
    check: Callable[[T], None] | None = None,
) -> StructuredResult[T]:
    """Call the judge and validate its reply; on failure retry once with the error.

    Raises JudgeOutputError when the repaired reply is still unusable.
    """
    raw = await llm.complete(
        system=system, user=user, model=options.model, temperature=options.temperature
    )
    try:
        return StructuredResult(_parse(raw, schema, check), 1)
    except ValueError as exc:
        first_error = _describe(exc)

    history = [
        {"role": "assistant", "content": raw if raw.strip() else "(empty reply)"},
        {"role": "user", "content": REPAIR_INSTRUCTION.format(error=first_error)},
    ]
    repaired = await llm.complete(
        system=system,
        user=user,
        model=options.model,
        temperature=options.temperature,
        history=history,
    )
    try:
        return StructuredResult(_parse(repaired, schema, check), 2)
    except ValueError as exc:
        raise JudgeOutputError(_describe(exc), raw=repaired) from exc


def _parse[T: BaseModel](raw: str, schema: type[T], check: Callable[[T], None] | None) -> T:
    value = schema.model_validate(extract_json_object(raw))
    if check is not None:
        check(value)
    return value


def _describe(exc: ValueError) -> str:
    # pydantic's ValidationError subclasses ValueError.
    if isinstance(exc, ValidationError):
        parts = []
        for err in exc.errors()[:5]:
            loc = ".".join(str(p) for p in err["loc"])
            parts.append(f"{loc}: {err['msg']}" if loc else str(err["msg"]))
        return "; ".join(parts)
    return str(exc)
