from __future__ import annotations

from typing import Sequence

from opentelemetry.sdk.trace import TracerProvider


def activate_instrumentors(
    keys: Sequence[str] | None,
    tracer_provider: TracerProvider,
) -> list[str]:
    """Activate OpenInference instrumentors. Stub until Task 4."""
    return []
