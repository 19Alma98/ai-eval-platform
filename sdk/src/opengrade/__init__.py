"""opengrade — OTLP + OpenInference tracing and platform control-plane client."""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version
from typing import Any

from opengrade._config import get_tracking_uri, set_tracking_uri
from opengrade._otel import flush, init
from opengrade._trace import (
    current_trace_id,
    set_attribute,
    set_attributes,
    set_error,
    set_input,
    set_output,
    trace,
    trace_async,
)
from opengrade.feedback import log_feedback, log_score, score_trace
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
    "aset_project": ("opengrade._context", "aset_project"),
    "bind_evaluation": ("opengrade._eval_run", "bind_evaluation"),
    "evaluate": ("opengrade.experiment", "evaluate"),
    "get_async_client": ("opengrade._context", "get_async_client"),
    "get_client": ("opengrade._context", "get_client"),
    "get_project": ("opengrade._context", "get_project"),
    "log_metrics": ("opengrade.experiment", "log_metrics"),
    "log_params": ("opengrade.experiment", "log_params"),
    "set_project": ("opengrade._context", "set_project"),
    "set_retrieval_documents": ("opengrade._eval_run", "set_retrieval_documents"),
    "start_experiment": ("opengrade.experiment", "start_experiment"),
}

__all__ = [
    "__version__",
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
    "LocalMetric",
    "Sample",
    "Score",
    "aset_project",
    "bind_evaluation",
    "current_trace_id",
    "evaluate",
    "flush",
    "get_async_client",
    "get_client",
    "get_project",
    "get_tracking_uri",
    "init",
    "log_feedback",
    "log_metrics",
    "log_params",
    "log_score",
    "metric",
    "score_trace",
    "set_attribute",
    "set_attributes",
    "set_error",
    "set_input",
    "set_output",
    "set_project",
    "set_retrieval_documents",
    "set_tracking_uri",
    "start_experiment",
    "trace",
    "trace_async",
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
    return sorted(__all__)


try:
    __version__ = _version("opengrade-ai")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0"
