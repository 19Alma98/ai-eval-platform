"""opengrade — OTLP + OpenInference tracing and platform control-plane client."""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from opengrade._errors import OpengradeAPIError as OpengradeAPIError
    from opengrade._errors import OpengradeConnectionError as OpengradeConnectionError
    from opengrade._errors import OpengradeError as OpengradeError
    from opengrade._eval_run import bind_evaluation as bind_evaluation
    from opengrade._eval_run import set_retrieval_documents as set_retrieval_documents
    from opengrade._eval_run import set_search_query as set_search_query
    from opengrade._opengrade import Opengrade as Opengrade
    from opengrade._opengrade import current as current
    from opengrade._state import Settings as Settings
    from opengrade.async_client import AsyncClient as AsyncClient
    from opengrade.chat import ChatTurn as ChatTurn
    from opengrade.chat import RagChatInput as RagChatInput
    from opengrade.chat import chat_input as chat_input
    from opengrade.client import Client as Client
    from opengrade.experiment import DatasetColumnError as DatasetColumnError
    from opengrade.experiment import Experiment as Experiment
    from opengrade.experiment import ExperimentResult as ExperimentResult
    from opengrade.experiment import ItemRun as ItemRun
    from opengrade.judges import LlmJudge as LlmJudge
    from opengrade.registry import AppConfigClient as AppConfigClient
    from opengrade.sweeps import SweepResult as SweepResult
    from opengrade.sweeps import SweepRun as SweepRun

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
    __version__ = _version("opengrade-ai")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"
