from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from opengrade_server.domain.rag_qa import validate_rag_qa_item

_QUESTION_KEYS = ("question", "input")
_ANSWER_KEYS = ("expected_answer", "expected_output")
_DOC_IDS_KEY = "expected_doc_ids"


@dataclass(frozen=True, slots=True)
class ParsedImportRows:
    rows: list[dict[str, Any]]
    """1-based row number for rows[0]."""

    first_row_number: int


def _has_any(fieldnames: list[str] | None, *names: str) -> bool:
    if not fieldnames:
        return False
    present = set(fieldnames)
    return any(name in present for name in names)


def _missing_csv_columns(fieldnames: list[str] | None) -> list[str]:
    missing: list[str] = []
    if not _has_any(fieldnames, *_QUESTION_KEYS):
        missing.append("question (or input)")
    if not _has_any(fieldnames, *_ANSWER_KEYS):
        missing.append("expected_answer (or expected_output)")
    if not _has_any(fieldnames, _DOC_IDS_KEY):
        missing.append(_DOC_IDS_KEY)
    return missing


def _parse_jsonl(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONL line {line_no} is not valid JSON") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"JSONL line {line_no} must be a JSON object")
        rows.append(obj)
    return rows


def parse_import_payload(
    *,
    filename: str | None,
    raw: bytes,
    format: str | None = None,
) -> ParsedImportRows:
    fmt = (format or "").lower().strip()
    name = (filename or "").lower()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("import file must be UTF-8") from exc
    is_jsonl = fmt == "jsonl" or name.endswith(".jsonl")
    if is_jsonl:
        return ParsedImportRows(rows=_parse_jsonl(text), first_row_number=1)
    is_json = fmt == "json" or name.endswith(".json") or text.lstrip().startswith("[")
    if is_json:
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("JSON import must be an array of objects")
        return ParsedImportRows(rows=data, first_row_number=1)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("CSV has no header")
    missing = _missing_csv_columns(list(reader.fieldnames))
    if missing:
        raise ValueError(f"CSV missing columns: {', '.join(missing)}")
    return ParsedImportRows(rows=list(reader), first_row_number=2)


def _coerce_expected_doc_ids(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return value
            if isinstance(parsed, list):
                return parsed
    return value


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def row_to_item_fields(row: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    question = _first_present(row, "input", "question")
    answer = _first_present(row, "expected_output", "expected_answer")
    doc_ids = _coerce_expected_doc_ids(row.get("expected_doc_ids"))
    metadata: dict[str, Any] = {"expected_doc_ids": doc_ids}
    if "must_contain" in row:
        metadata["must_contain"] = _coerce_expected_doc_ids(row.get("must_contain"))
    meta = validate_rag_qa_item(
        input=question,
        expected_output=answer,
        metadata=metadata,
    )
    return str(question).strip(), str(answer).strip(), meta
