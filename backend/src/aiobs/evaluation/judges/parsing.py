from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


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
