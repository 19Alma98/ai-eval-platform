from __future__ import annotations

from aiobs.infrastructure.repositories import escape_like


def test_escape_like_escapes_wildcards_and_backslash() -> None:
    assert escape_like("50%_a\\b") == "50\\%\\_a\\\\b"


def test_escape_like_leaves_plain_text() -> None:
    assert escape_like("ferie 2026") == "ferie 2026"
