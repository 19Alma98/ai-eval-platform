"""Tiny printing helpers so the tour output reads like a walkthrough."""

from __future__ import annotations

import textwrap


def title(text: str) -> None:
    print(f"\n{'=' * 78}\n{text}\n{'=' * 78}")


def step(number: int | str, text: str) -> None:
    print(f"\n--- Step {number}: {text} " + "-" * max(0, 64 - len(text)))


def note(text: str) -> None:
    print(textwrap.indent(textwrap.fill(" ".join(text.split()), 76), "  > "))
