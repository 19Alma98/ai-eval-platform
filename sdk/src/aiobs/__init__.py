"""aiobs — OTLP + OpenInference tracing and platform control-plane client."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from aiobs._config import get_tracking_uri, set_tracking_uri
from aiobs._context import get_client, get_project, set_project
from aiobs._eval_run import bind_evaluation, set_retrieval_documents
from aiobs._http import AiobsAPIError
from aiobs._otel import flush, init
from aiobs._trace import (
    current_trace_id,
    set_attribute,
    set_attributes,
    set_error,
    set_input,
    set_output,
    trace,
    trace_async,
)
from aiobs.client import Client
from aiobs.experiment import (
    Experiment,
    ExperimentResult,
    ItemRun,
    LocalMetric,
    evaluate,
    log_metrics,
    log_params,
    start_experiment,
)
from aiobs.feedback import log_feedback, log_score, score
from aiobs.metrics import Sample, Score, metric
from aiobs.registry import AppConfigClient

__all__ = [
    "__version__",
    "AiobsAPIError",
    "AppConfigClient",
    "Client",
    "Experiment",
    "ExperimentResult",
    "ItemRun",
    "LocalMetric",
    "Sample",
    "Score",
    "bind_evaluation",
    "current_trace_id",
    "evaluate",
    "flush",
    "get_client",
    "get_project",
    "get_tracking_uri",
    "init",
    "log_feedback",
    "log_metrics",
    "log_params",
    "log_score",
    "metric",
    "score",
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
    __version__ = _version("aiobs-eval")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0"
