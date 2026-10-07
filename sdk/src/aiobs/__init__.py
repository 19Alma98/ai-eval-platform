"""aiobs — OTLP + OpenInference tracing and platform control-plane client."""

from __future__ import annotations

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
from aiobs.registry import AppConfigClient

__all__ = [
    "__version__",
    "AiobsAPIError",
    "AppConfigClient",
    "Client",
    "bind_evaluation",
    "current_trace_id",
    "flush",
    "init",
    "set_attribute",
    "set_attributes",
    "set_error",
    "set_input",
    "set_output",
    "set_retrieval_documents",
    "trace",
    "trace_async",
]
__version__ = "0.1.0"
