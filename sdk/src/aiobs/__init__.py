"""aiobs — thin OTLP + OpenInference client SDK."""

from __future__ import annotations

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
from aiobs.registry import AppConfigClient

__all__ = [
    "__version__",
    "AppConfigClient",
    "current_trace_id",
    "flush",
    "init",
    "set_attribute",
    "set_attributes",
    "set_error",
    "set_input",
    "set_output",
    "trace",
    "trace_async",
]
__version__ = "0.1.0"
