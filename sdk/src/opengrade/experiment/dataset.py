from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from opengrade.client import Client
from opengrade.experiment.serialization import _digest, _jsonable
from opengrade.models import DatasetResponse

logger = logging.getLogger("opengrade")


_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-?([0-9a-fA-F]{4}-?){3}[0-9a-fA-F]{12}$")
_ITEM_KEYS = frozenset({"input", "expected_output", "context", "metadata"})
_INPUT_KEYS = frozenset({"input", "question"})
_COLUMN_ALIASES = (
    ("question", "input"),
    ("expected_answer", "expected_output"),
)
_COLUMN_HELP = (
    "Required: 'input' (or alias 'question'). "
    "Optional: 'expected_output' (or 'expected_answer'), 'context', 'metadata'; "
    "other columns go into metadata (e.g. expected_doc_ids, must_contain)."
)


class DatasetColumnError(ValueError):
    """Raised when a dataset row or CSV header is missing required columns."""

    def __init__(
        self,
        *,
        missing: Sequence[str],
        found: Sequence[str],
        row_index: int | None = None,
        path: str | Path | None = None,
    ) -> None:
        self.missing = list(missing)
        self.found = list(found)
        self.row_index = row_index
        self.path = None if path is None else str(path)
        parts: list[str] = []
        if self.path is not None:
            parts.append(self.path)
        if row_index is not None:
            parts.append(f"row {row_index}")
        where = ": ".join(parts) if parts else "dataset"
        super().__init__(
            f"{where} missing column(s) {self.missing}; found {self.found}. {_COLUMN_HELP}"
        )


def _is_uuid(value: str) -> bool:
    return bool(_UUID_RE.match(value.strip()))


def _has_input_column(columns: Iterable[str | None] | None) -> bool:
    if columns is None:
        return False
    return bool(_INPUT_KEYS.intersection(c for c in columns if c))


DatasetLike = (
    str | Path | DatasetResponse | Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]] | Any
)


def _canonicalize_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for alias, canonical in _COLUMN_ALIASES:
        if alias not in out:
            continue
        if canonical not in out or out[canonical] is None:
            out[canonical] = out[alias]
        del out[alias]
    return out


def _load_file_records(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"dataset file must be UTF-8: {path}") from exc
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        records: list[dict[str, Any]] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}: JSONL line {line_no} is not valid JSON") from exc
            if not isinstance(obj, Mapping):
                raise TypeError(f"{path}: JSONL line {line_no} must be a JSON object")
            records.append(_jsonable(dict(obj)))
        return records
    if suffix == ".json" or text.lstrip().startswith("["):
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError(f"{path}: JSON dataset must be an array of objects")
        if not all(isinstance(row, Mapping) for row in data):
            raise TypeError(f"{path}: JSON dataset must contain objects")
        return [_jsonable(dict(row)) for row in data]
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError(f"{path}: CSV has no header")
    found = [c for c in reader.fieldnames if c]
    if not _has_input_column(found):
        raise DatasetColumnError(
            missing=["input (or question)"],
            found=found,
            path=path,
        )
    return [_jsonable(dict(row)) for row in reader]


def _mapping_rows(rows: Iterable[Any], *, label: str) -> list[dict[str, Any]]:
    materialised = list(rows)
    if not all(isinstance(row, Mapping) for row in materialised):
        raise TypeError(f"{label} must contain dicts")
    return [_jsonable(dict(row)) for row in materialised]


def _records_from(dataset: Any) -> list[dict[str, Any]] | None:
    if isinstance(dataset, Path):
        if not dataset.is_file():
            raise ValueError(f"dataset path does not exist: {dataset}")
        return _load_file_records(dataset)
    # Polars before pandas: Polars uses to_dicts(); pandas uses to_json(orient=...).
    if callable(getattr(dataset, "to_dicts", None)) and hasattr(dataset, "columns"):
        return _mapping_rows(dataset.to_dicts(), label="polars DataFrame")
    if hasattr(dataset, "to_json") and hasattr(dataset, "columns"):  # pandas DataFrame
        records = json.loads(dataset.to_json(orient="records", date_format="iso"))
        return [dict(r) for r in records]
    if isinstance(dataset, Sequence) and not isinstance(dataset, (str, bytes)):
        return _mapping_rows(dataset, label="dataset list")
    if isinstance(dataset, Iterable) and not isinstance(dataset, (str, bytes, Mapping)):
        return _mapping_rows(dataset, label="dataset iterable")
    return None


def _parse_json_column(key: str, value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"dataset column {key!r} must be valid JSON: {exc.msg}") from exc


def _normalize_item_value(key: str, value: Any) -> Any:
    """CSV empty cells become ``None``; ``metadata``/``context`` strings are JSON."""
    if value == "":
        return None
    if key in ("metadata", "context") and isinstance(value, str):
        return _parse_json_column(key, value)
    return value


def _item_body(row: dict[str, Any], index: int) -> dict[str, Any]:
    raw_keys = sorted(row)
    row = _canonicalize_row(row)
    if "input" not in row or row.get("input") in (None, ""):
        raise DatasetColumnError(
            missing=["input (or question)"],
            found=raw_keys,
            row_index=index,
        )
    normalized = {k: _normalize_item_value(k, v) for k, v in row.items()}
    body = {k: normalized[k] for k in _ITEM_KEYS if normalized.get(k) is not None}
    extras = {
        k: v for k, v in normalized.items() if k not in _ITEM_KEYS and v is not None and v != ""
    }
    if extras:
        body["metadata"] = {**extras, **dict(body.get("metadata") or {})}
    return body


def _inline_dataset_id(
    client: Client,
    project_id: str,
    records: list[dict[str, Any]],
    *,
    task_type: str,
) -> str:
    if not records:
        raise ValueError("dataset is empty")
    bodies = [_item_body(row, i) for i, row in enumerate(records)]
    # Content-addressed name: re-running on the same rows reuses the dataset, so runs
    # stay comparable against each other.
    name = f"inline-{_digest([task_type, bodies])[:12]}"
    expected = len(bodies)
    for existing in client.datasets.list(project_id, name=name):
        detail = client.datasets.get(existing.id)
        have = len(detail.items)
        if have == expected:
            return existing.id
        if have > expected:
            # Unexpected extra rows: mint a fresh name rather than reuse a bad set.
            name = f"{name}-r{_digest(existing.id)[:6]}"
            break
        # Partial create from a previous interrupted upload — resume remaining items.
        client.datasets.ensure_items(existing.id, bodies)
        logger.info("opengrade resumed dataset %s (%d → %d items)", existing.name, have, expected)
        return existing.id
    created = client.datasets.create_with_items(
        project_id,
        name=name,
        items=bodies,
        task_type=task_type,
        description="Created by opengrade.evaluate() from in-memory rows",
    )
    logger.info("opengrade created dataset %s (%d items)", name, len(bodies))
    return created.id


def _resolve_dataset(
    client: Client, project_id: str, dataset: DatasetLike, *, task_type: str
) -> str:
    if isinstance(dataset, DatasetResponse):
        return dataset.id
    if isinstance(dataset, Path):
        if not dataset.is_file():
            raise ValueError(f"dataset path does not exist: {dataset}")
        return _inline_dataset_id(
            client, project_id, _load_file_records(dataset), task_type=task_type
        )
    if isinstance(dataset, str):
        if _is_uuid(dataset):
            return dataset
        # Existing file path wins over a registered dataset name (e.g. "gold.csv").
        if os.path.isfile(dataset):
            return _inline_dataset_id(
                client, project_id, _load_file_records(Path(dataset)), task_type=task_type
            )
        matches = client.datasets.list(project_id, name=dataset)
        if not matches:
            raise ValueError(f"no dataset named {dataset!r} in project {project_id}")
        return max(matches, key=lambda d: d.version).id

    records = _records_from(dataset)
    if records is None:
        raise TypeError(
            "dataset must be a name, id, DatasetResponse, file path, list/iterable of "
            f"dicts, pandas DataFrame or Polars DataFrame; got {type(dataset).__name__}"
        )
    return _inline_dataset_id(client, project_id, records, task_type=task_type)
