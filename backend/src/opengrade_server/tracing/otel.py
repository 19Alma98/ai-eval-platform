"""OTLP HTTP decode helpers (protobuf + OTLP/JSON)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)


class OtlpDecodeError(ValueError):
    pass


def _nanos_to_datetime(nanos: int | str | None) -> datetime | None:
    if nanos is None or nanos == "" or nanos == 0:
        return None
    value = int(nanos)
    if value <= 0:
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC)


def _status_code_name(code: int | str | None) -> str:
    if code in (2, "STATUS_CODE_ERROR", "ERROR", "error"):
        return "error"
    if code in (1, "STATUS_CODE_OK", "OK", "ok"):
        return "ok"
    return "unset"


def _attr_value_proto(value: Any) -> Any:
    which = value.WhichOneof("value")
    if which is None:
        return None
    raw = getattr(value, which)
    if which == "array_value":
        return [_attr_value_proto(v) for v in raw.values]
    if which == "kvlist_value":
        return {item.key: _attr_value_proto(item.value) for item in raw.values}
    return raw


def _attr_value_json(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, dict):
        return value
    for key in (
        "stringValue",
        "boolValue",
        "intValue",
        "doubleValue",
        "bytesValue",
    ):
        if key in value:
            return value[key]
    if "arrayValue" in value:
        values = (value.get("arrayValue") or {}).get("values") or []
        return [_attr_value_json(v) for v in values]
    if "kvlistValue" in value:
        values = (value.get("kvlistValue") or {}).get("values") or []
        return {
            item.get("key"): _attr_value_json(item.get("value"))
            for item in values
            if item.get("key")
        }
    return value


def _attributes_proto(attributes: Any) -> dict[str, Any]:
    return {attr.key: _attr_value_proto(attr.value) for attr in attributes or []}


def _attributes_json(attributes: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for attr in attributes or []:
        key = attr.get("key")
        if key:
            result[key] = _attr_value_json(attr.get("value"))
    return result


def _events_proto(events: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": event.name,
            "time_unix_nano": event.time_unix_nano,
            "attributes": _attributes_proto(event.attributes),
        }
        for event in events or []
    ]


def _events_json(events: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for event in events or []:
        out.append(
            {
                "name": event.get("name"),
                "time_unix_nano": event.get("timeUnixNano"),
                "attributes": _attributes_json(event.get("attributes") or []),
            }
        )
    return out


def _hex_id(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    text = str(value).strip()
    return text.lower()


def iter_raw_spans_from_proto(request: ExportTraceServiceRequest) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for resource_spans in request.resource_spans:
        resource_attrs = _attributes_proto(resource_spans.resource.attributes)
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                parent = span.parent_span_id.hex() if span.parent_span_id else None
                spans.append(
                    {
                        "trace_id": span.trace_id.hex(),
                        "span_id": span.span_id.hex(),
                        "parent_span_id": parent or None,
                        "name": span.name,
                        "start_time": _nanos_to_datetime(span.start_time_unix_nano),
                        "end_time": _nanos_to_datetime(span.end_time_unix_nano),
                        "status": _status_code_name(span.status.code),
                        "attributes": {
                            **resource_attrs,
                            **_attributes_proto(span.attributes),
                        },
                        "events": _events_proto(span.events),
                        "kind_code": span.kind,
                    }
                )
    return spans


def iter_raw_spans_from_json(payload: dict[str, Any]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for resource_spans in payload.get("resourceSpans") or payload.get("resource_spans") or []:
        resource = resource_spans.get("resource") or {}
        resource_attrs = _attributes_json(resource.get("attributes") or [])
        scope_list = resource_spans.get("scopeSpans") or resource_spans.get("scope_spans") or []
        for scope_spans in scope_list:
            for span in scope_spans.get("spans") or []:
                parent = _hex_id(span.get("parentSpanId") or span.get("parent_span_id"))
                status = span.get("status") or {}
                status_code = status.get("code") if isinstance(status, dict) else status
                spans.append(
                    {
                        "trace_id": _hex_id(span.get("traceId") or span.get("trace_id")),
                        "span_id": _hex_id(span.get("spanId") or span.get("span_id")),
                        "parent_span_id": parent or None,
                        "name": span.get("name") or "span",
                        "start_time": _nanos_to_datetime(
                            span.get("startTimeUnixNano") or span.get("start_time_unix_nano")
                        ),
                        "end_time": _nanos_to_datetime(
                            span.get("endTimeUnixNano") or span.get("end_time_unix_nano")
                        ),
                        "status": _status_code_name(status_code),
                        "attributes": {
                            **resource_attrs,
                            **_attributes_json(span.get("attributes") or []),
                        },
                        "events": _events_json(span.get("events") or []),
                        "kind_code": span.get("kind"),
                    }
                )
    return spans


def decode_otlp_to_raw_spans(body: bytes, content_type: str | None) -> list[dict[str, Any]]:
    ct = (content_type or "").split(";")[0].strip().lower()
    try:
        if ct == "application/json" or ct.endswith("+json"):
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise OtlpDecodeError("OTLP JSON root must be an object")
            return iter_raw_spans_from_json(payload)

        request = ExportTraceServiceRequest()
        request.ParseFromString(body)
        return iter_raw_spans_from_proto(request)
    except OtlpDecodeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OtlpDecodeError(f"Invalid OTLP payload: {exc}") from exc
