from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aiobs.evaluation.protocol import Evaluator

EvaluatorFactory = Callable[[dict[str, Any]], Evaluator]

_REGISTRY: dict[str, EvaluatorFactory] = {}


def register_evaluator(kind: str, factory: EvaluatorFactory) -> None:
    key = kind.strip().lower()
    if not key:
        raise ValueError("Evaluator kind must not be empty")
    _REGISTRY[key] = factory


def get_evaluator_factory(kind: str) -> EvaluatorFactory:
    key = kind.strip().lower()
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(f"Unknown evaluator kind '{kind}'. Known: {known}") from exc


def create_evaluator(kind: str, config: dict[str, Any]) -> Evaluator:
    factory = get_evaluator_factory(kind)
    return factory(config)


def list_registered_kinds() -> list[str]:
    return sorted(_REGISTRY)


def clear_registry() -> None:
    """Test helper — clears all registered evaluators."""
    _REGISTRY.clear()
