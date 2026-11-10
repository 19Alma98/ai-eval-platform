"""opengrade — OTLP + OpenInference tracing and platform control-plane client."""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version
from typing import Any

from opengrade._trace import (
    current_trace_id,
    set_attribute,
    set_attributes,
    set_error,
    set_input,
    set_output,
    span,
    trace,
)
from opengrade._trace_attrs import (
    set_metadata,
    set_session,
    set_tags,
    set_user,
    using_attributes,
)
from opengrade.metrics import LocalMetric, Sample, Score, metric

# Heavy modules (httpx2, pydantic, experiment stack) load on first attribute access.
_LAZY: dict[str, tuple[str, str]] = {
    "OpengradeAPIError": ("opengrade._errors", "OpengradeAPIError"),
    "OpengradeConnectionError": ("opengrade._errors", "OpengradeConnectionError"),
    "OpengradeError": ("opengrade._errors", "OpengradeError"),
    "AppConfigClient": ("opengrade.registry", "AppConfigClient"),
    "AsyncClient": ("opengrade.async_client", "AsyncClient"),
    "Client": ("opengrade.client", "Client"),
    "DatasetColumnError": ("opengrade.experiment", "DatasetColumnError"),
    "Experiment": ("opengrade.experiment", "Experiment"),
    "ExperimentResult": ("opengrade.experiment", "ExperimentResult"),
    "ItemRun": ("opengrade.experiment", "ItemRun"),
    "LlmJudge": ("opengrade.judges", "LlmJudge"),
    "SweepResult": ("opengrade.sweeps", "SweepResult"),
    "SweepRun": ("opengrade.sweeps", "SweepRun"),
    "Opengrade": ("opengrade._opengrade", "Opengrade"),
    "Settings": ("opengrade._state", "Settings"),
    "current": ("opengrade._opengrade", "current"),
    "bind_evaluation": ("opengrade._eval_run", "bind_evaluation"),
    "ChatTurn": ("opengrade.chat", "ChatTurn"),
    "RagChatInput": ("opengrade.chat", "RagChatInput"),
    "chat_input": ("opengrade.chat", "chat_input"),
    "set_retrieval_documents": ("opengrade._eval_run", "set_retrieval_documents"),
    "set_search_query": ("opengrade._eval_run", "set_search_query"),
}

__all__ = [
    "__version__",
    "Opengrade",
    "Settings",
    "current",
    "OpengradeAPIError",
    "OpengradeConnectionError",
    "OpengradeError",
    "AppConfigClient",
    "AsyncClient",
    "Client",
    "DatasetColumnError",
    "Experiment",
    "ExperimentResult",
    "ItemRun",
    "LlmJudge",
    "SweepResult",
    "SweepRun",
    "LocalMetric",
    "Sample",
    "Score",
    "bind_evaluation",
    "ChatTurn",
    "RagChatInput",
    "chat_input",
    "current_trace_id",
    "metric",
    "set_attribute",
    "set_attributes",
    "set_error",
    "set_input",
    "set_metadata",
    "set_output",
    "set_retrieval_documents",
    "set_search_query",
    "set_session",
    "set_tags",
    "set_user",
    "span",
    "trace",
    "using_attributes",
]


def __getattr__(name: str) -> Any:
    try:
        module_name, attr = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(import_module(module_name), attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()) | set(_LAZY))


try:
    __version__ = _version("opengrade")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"
