"""opengrade — OTLP + OpenInference tracing and platform control-plane client."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from opengrade._config import get_tracking_uri, set_tracking_uri
from opengrade._context import aset_project, get_async_client, get_client, get_project, set_project
from opengrade._eval_run import bind_evaluation, set_retrieval_documents
from opengrade._http import OpengradeAPIError, OpengradeConnectionError, OpengradeError
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
from opengrade.async_client import AsyncClient
from opengrade.client import Client
from opengrade.experiment import (
    DatasetColumnError,
    Experiment,
    ExperimentResult,
    ItemRun,
    LocalMetric,
    evaluate,
    log_metrics,
    log_params,
    start_experiment,
)
from opengrade.feedback import log_feedback, log_score, score_trace
from opengrade.metrics import Sample, Score, metric
from opengrade.registry import AppConfigClient

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

try:
    __version__ = _version("opengrade-ai")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0"
