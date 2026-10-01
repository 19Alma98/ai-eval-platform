"""Minimal OTLP hello example: emit one CHAIN span to the platform."""

from __future__ import annotations

import os
import time

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def main() -> None:
    endpoint = os.getenv("AIOBS_OTLP_ENDPOINT", "http://localhost:8000/v1/traces")
    project_id = os.getenv("AIOBS_PROJECT_ID")
    project_slug = os.getenv("AIOBS_PROJECT_SLUG", "demo")

    headers: dict[str, str] = {}
    if project_id:
        headers["X-Project-Id"] = project_id
    else:
        headers["X-Project-Slug"] = project_slug

    resource = Resource.create({"service.name": "otlp-hello"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    tracer = trace.get_tracer("otlp-hello")
    with tracer.start_as_current_span("hello-chain") as span:
        span.set_attribute("openinference.span.kind", "CHAIN")
        span.set_attribute("input.value", "hello (redacted by default)")
        time.sleep(0.05)

    provider.force_flush()
    print(f"Exported OTLP spans to {endpoint} (project header={headers})")


if __name__ == "__main__":
    main()
