from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from aiobs.domain.rag_qa import validate_rag_qa_item

REQUIRED = ("question", "expected_answer", "expected_doc_ids")


@dataclass(frozen=True, slots=True)
class ParsedImportRows:
    rows: list[dict[str, Any]]
    """1-based row number for rows[0]."""

    first_row_number: int


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
    is_json = fmt == "json" or name.endswith(".json") or text.lstrip().startswith("[")
    if is_json:
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("JSON import must be an array of objects")
        return ParsedImportRows(rows=data, first_row_number=1)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("CSV has no header")
    missing = [c for c in REQUIRED if c not in reader.fieldnames]
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


def row_to_item_fields(row: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    question = row.get("question")
    answer = row.get("expected_answer")
    doc_ids = _coerce_expected_doc_ids(row.get("expected_doc_ids"))
    meta = validate_rag_qa_item(
        input=question,
        expected_output=answer,
        metadata={"expected_doc_ids": doc_ids},
    )
    return str(question).strip(), str(answer).strip(), meta
