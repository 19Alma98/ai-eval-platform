from __future__ import annotations

import importlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from opentelemetry.sdk.trace import TracerProvider

logger = logging.getLogger("aiobs")


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
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def _any_target_available(spec: InstrumentorSpec) -> bool:
    return any(_module_available(m) for m in spec.target_modules)


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
            logger.debug("aiobs: skip %s (target library not installed)", key)
            continue
        if not _module_available(spec.instrumentor_module):
            logger.debug("aiobs: skip %s (OpenInference instrumentor not installed)", key)
            continue
        module = importlib.import_module(spec.instrumentor_module)
        cls = getattr(module, spec.instrumentor_class)
        cls().instrument(tracer_provider=tracer_provider)
        activated.append(key)
        logger.info("aiobs: activated OpenInference instrumentor %s", key)

    return activated
