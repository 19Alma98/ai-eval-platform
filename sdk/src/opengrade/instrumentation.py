from __future__ import annotations

import importlib
import importlib.util
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from opentelemetry.sdk.trace import TracerProvider

logger = logging.getLogger("opengrade")

# Instrumentor instances activated by the last ``activate_instrumentors`` call.
_ACTIVE: list[Any] = []


@dataclass(frozen=True, slots=True)
class InstrumentorSpec:
    target_modules: tuple[str, ...]
    instrumentor_module: str
    instrumentor_class: str


TIER1: dict[str, InstrumentorSpec] = {
    "openai": InstrumentorSpec(
        target_modules=("openai",),
        instrumentor_module="openinference.instrumentation.openai",
        instrumentor_class="OpenAIInstrumentor",
    ),
    "anthropic": InstrumentorSpec(
        target_modules=("anthropic",),
        instrumentor_module="openinference.instrumentation.anthropic",
        instrumentor_class="AnthropicInstrumentor",
    ),
    "langchain": InstrumentorSpec(
        target_modules=("langchain_core", "langchain"),
        instrumentor_module="openinference.instrumentation.langchain",
        instrumentor_class="LangChainInstrumentor",
    ),
    "llama_index": InstrumentorSpec(
        target_modules=("llama_index",),
        instrumentor_module="openinference.instrumentation.llama_index",
        instrumentor_class="LlamaIndexInstrumentor",
    ),
    "bedrock": InstrumentorSpec(
        target_modules=("boto3",),
        instrumentor_module="openinference.instrumentation.bedrock",
        instrumentor_class="BedrockInstrumentor",
    ),
}


def _module_available(name: str) -> bool:
    """True if ``name`` can be imported, without executing the module."""
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:  # noqa: BLE001 — probe may raise beyond ImportError
        return False


def _any_target_available(spec: InstrumentorSpec) -> bool:
    return any(_module_available(m) for m in spec.target_modules)


def deactivate_instrumentors() -> None:
    """Call ``uninstrument()`` on every instrumentor we previously activated."""
    global _ACTIVE
    for instrumentor in _ACTIVE:
        try:
            instrumentor.uninstrument()
        except Exception as exc:  # noqa: BLE001 — teardown must not break re-init
            logger.debug("opengrade: uninstrument failed: %s", exc)
    _ACTIVE = []


def activate_instrumentors(
    keys: Sequence[str] | None,
    tracer_provider: TracerProvider,
) -> list[str]:
    selected = list(TIER1.keys()) if keys is None else list(keys)
    activated: list[str] = []

    for key in selected:
        spec = TIER1.get(key)
        if spec is None:
            raise ValueError(f"unknown instrumentor key: {key!r}; known={sorted(TIER1)}")
        if not _any_target_available(spec):
            logger.debug("opengrade: skip %s (target library not installed)", key)
            continue
        if not _module_available(spec.instrumentor_module):
            logger.debug("opengrade: skip %s (OpenInference instrumentor not installed)", key)
            continue
        try:
            module = importlib.import_module(spec.instrumentor_module)
            cls = getattr(module, spec.instrumentor_class)
            instrumentor = cls()
            instrumentor.instrument(tracer_provider=tracer_provider)
        except Exception as exc:  # noqa: BLE001 — a broken instrumentor must not break the app
            logger.warning("opengrade: could not activate instrumentor %s: %s", key, exc)
            continue
        _ACTIVE.append(instrumentor)
        activated.append(key)
        logger.info("opengrade: activated OpenInference instrumentor %s", key)

    return activated
