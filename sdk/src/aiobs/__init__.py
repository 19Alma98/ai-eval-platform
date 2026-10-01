"""aiobs — thin OTLP + OpenInference client SDK."""

from __future__ import annotations

from aiobs._otel import flush, init
from aiobs._trace import trace, trace_async

__all__ = ["__version__", "flush", "init", "trace", "trace_async"]
__version__ = "0.1.0"
