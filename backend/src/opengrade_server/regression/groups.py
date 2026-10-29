"""Slice results by a dataset-item metadata field (e.g. ``category``, ``language``).

A global mean can hide a regression on one kind of question; grouping reports the same
aggregates and comparisons per group value.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from opengrade_server.domain.dataset import DatasetItem
from opengrade_server.domain.evaluation import EvaluationResultRecord

NO_VALUE = "(none)"
MAX_GROUPS = 50
GROUP_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+(\.[A-Za-z0-9_\-]+)*$")


class InvalidGroupKeyError(ValueError):
    pass


def validate_group_key(key: str) -> str:
    cleaned = key.strip()
    if not cleaned or len(cleaned) > 200 or not GROUP_KEY_PATTERN.fullmatch(cleaned):
        raise InvalidGroupKeyError(
            f"group_by must be a metadata key path like 'category' or 'tags.lang', got {key!r}"
        )
    return cleaned


def _lookup(metadata: Mapping[str, Any], path: str) -> Any:
    value: Any = metadata
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _labels(value: Any) -> list[str]:
    if value is None or value == "":
        return [NO_VALUE]
    if isinstance(value, list | tuple):
        # A list (e.g. tags) puts the item in every group it names.
        labels = sorted({label for v in value for label in _labels(v)})
        return labels or [NO_VALUE]
    if isinstance(value, bool):
        return ["true" if value else "false"]
    if isinstance(value, Mapping):
        return [NO_VALUE]
    return [str(value)]


def item_groups(items: Iterable[DatasetItem], key: str) -> dict[str, set[uuid.UUID]]:
    """Group value -> dataset item ids, ordered by value. Raises past ``MAX_GROUPS``."""
    path = validate_group_key(key)
    groups: dict[str, set[uuid.UUID]] = {}
    for item in items:
        for label in _labels(_lookup(item.metadata, path)):
            groups.setdefault(label, set()).add(item.id)
    if len(groups) > MAX_GROUPS:
        raise InvalidGroupKeyError(
            f"group_by {key!r} has {len(groups)} distinct values (max {MAX_GROUPS}); "
            "group by a coarser field"
        )
    return dict(sorted(groups.items()))


def results_in(
    results: Iterable[EvaluationResultRecord], item_ids: set[uuid.UUID]
) -> list[EvaluationResultRecord]:
    return [r for r in results if r.dataset_item_id in item_ids]
