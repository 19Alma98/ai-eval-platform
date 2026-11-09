from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from opengrade_server.domain.rag_chat import validate_rag_chat_item
from opengrade_server.domain.rag_qa import ANSWERABLE_KEYS, validate_rag_qa_item

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


def _missing_csv_columns(fieldnames: list[str] | None, *, task_type: str) -> list[str]:
    missing: list[str] = []
    if task_type == "rag_chat":
        # question may live inside a structured ``input`` column.
        if not _has_any(fieldnames, *_QUESTION_KEYS) and not _has_any(fieldnames, "history"):
            missing.append("question (or input) and/or history")
        elif not _has_any(fieldnames, *_QUESTION_KEYS):
            missing.append("question (or input)")
    elif not _has_any(fieldnames, *_QUESTION_KEYS):
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
    task_type: str = "rag_qa",
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
    missing = _missing_csv_columns(list(reader.fieldnames), task_type=task_type)
    if missing:
        raise ValueError(f"CSV missing columns: {', '.join(missing)}")
    return ParsedImportRows(rows=list(reader), first_row_number=2)


def _coerce_json_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def _coerce_expected_doc_ids(value: Any) -> Any:
    return _coerce_json_value(value)


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _row_metadata(row: dict[str, Any]) -> dict[str, Any]:
    doc_ids = _coerce_expected_doc_ids(row.get("expected_doc_ids"))
    metadata: dict[str, Any] = {"expected_doc_ids": doc_ids}
    if "must_contain" in row:
        metadata["must_contain"] = _coerce_expected_doc_ids(row.get("must_contain"))
    for key in ANSWERABLE_KEYS:
        value = row.get(key)
        if value is not None and not (isinstance(value, str) and not value.strip()):
            metadata[key] = value
    return metadata


def _chat_input_from_row(row: dict[str, Any]) -> Any:
    """Build rag_chat input from a flat import row or a structured ``input`` object."""
    raw_input = row.get("input")
    if isinstance(raw_input, dict) and ("question" in raw_input or "history" in raw_input):
        return raw_input
    if isinstance(raw_input, str):
        coerced = _coerce_json_value(raw_input)
        if isinstance(coerced, dict) and ("question" in coerced or "history" in coerced):
            return coerced

    question = _first_present(row, "question")
    if question is None and isinstance(raw_input, str):
        question = raw_input
    history_raw = row.get("history", [])
    history = _coerce_json_value(history_raw)
    if history_raw in (None, "") and "history" not in row:
        history = []
    return {"history": history if history is not None else [], "question": question}


def row_to_item_fields(
    row: dict[str, Any], *, task_type: str = "rag_qa"
) -> tuple[Any, str | None, dict[str, Any]]:
    """Question / chat input, reference answer and metadata of one import row.

    ``answerable`` / ``expected_refusal`` / ``should_refuse`` columns are kept: a row
    labelled unanswerable may leave ``expected_answer`` and ``expected_doc_ids`` empty.
    """
    answer = _first_present(row, "expected_output", "expected_answer")
    if isinstance(answer, str) and not answer.strip():
        answer = None  # empty CSV cell
    metadata = _row_metadata(row)

    if task_type == "rag_chat":
        item_input = _chat_input_from_row(row)
        normalised, meta = validate_rag_chat_item(
            input=item_input,
            expected_output=answer,
            metadata=metadata,
        )
        return normalised, None if answer is None else str(answer).strip(), meta

    question = _first_present(row, "input", "question")
    meta = validate_rag_qa_item(
        input=question,
        expected_output=answer,
        metadata=metadata,
    )
    return str(question).strip(), None if answer is None else str(answer).strip(), meta
