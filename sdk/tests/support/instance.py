"""Construct ``Opengrade`` instances for tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opengrade import Opengrade, Settings


def make_og(**settings: Any) -> Opengrade:
    fields = Settings.__dataclass_fields__
    clean = {k: v for k, v in settings.items() if k in fields}
    return Opengrade(Settings.from_env(**clean))


@contextmanager
def activated(og: Opengrade) -> Iterator[Opengrade]:
    with og.activate():
        yield og


def init_og(
    *,
    project_slug: str | None = "demo",
    project_id: str | None = None,
    **init_kw: Any,
) -> Opengrade:
    """Construct ``Opengrade`` and call ``init_tracing`` (common in OTEL tests)."""
    og = make_og(project_slug=project_slug, project_id=project_id)
    og.init_tracing(**init_kw)
    return og
