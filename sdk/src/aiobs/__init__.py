"""aiobs — thin OTLP + OpenInference client SDK."""

from __future__ import annotations

from aiobs._otel import flush, init

__all__ = ["__version__", "flush", "init"]
__version__ = "0.1.0"
