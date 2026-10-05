from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

_UNSET: Any = object()


@dataclass(frozen=True, slots=True)
class MetricsPackEntry:
    kind: str
    enabled: bool
    threshold: float | None
    config: dict[str, Any]
    evaluator_id: uuid.UUID | None
    removable: bool


DEFAULT_RAG_ENTRIES: tuple[MetricsPackEntry, ...] = (
    MetricsPackEntry(
        kind="hit_at_k",
        enabled=True,
        threshold=0.8,
        config={"k": 5},
        evaluator_id=None,
        removable=False,
    ),
    MetricsPackEntry(
        kind="must_contain",
        enabled=True,
        threshold=1.0,
        config={"case_sensitive": False},
        evaluator_id=None,
        removable=False,
    ),
    MetricsPackEntry(
        kind="groundedness",
        enabled=True,
        threshold=0.7,
        config={},
        evaluator_id=None,
        removable=False,
    ),
    MetricsPackEntry(
        kind="correctness",
        enabled=True,
        threshold=0.7,
        config={},
        evaluator_id=None,
        removable=False,
    ),
    MetricsPackEntry(
        kind="latency",
        enabled=True,
        threshold=None,
        config={"max_ms": 5000},
        evaluator_id=None,
        removable=False,
    ),
)


@dataclass(frozen=True, slots=True)
class MetricsPack:
    id: uuid.UUID
    project_id: uuid.UUID
    entries: tuple[MetricsPackEntry, ...]
    updated_at: datetime

    @classmethod
    def create(cls, project_id: uuid.UUID) -> MetricsPack:
        entries = tuple(replace(e, config=dict(e.config)) for e in DEFAULT_RAG_ENTRIES)
        return cls(
            id=uuid.uuid4(),
            project_id=project_id,
            entries=entries,
            updated_at=datetime.now(UTC),
        )

    def patch_entry(
        self,
        kind: str,
        *,
        enabled: bool | None = None,
        threshold: float | None | Any = _UNSET,
        config: dict[str, Any] | None = None,
    ) -> MetricsPack:
        cleaned = kind.strip()
        if not cleaned:
            raise ValueError("Metrics pack entry kind must not be empty")
        idx = _index_of_kind(self.entries, cleaned)
        if idx is None:
            raise ValueError(f"unknown metrics pack entry kind: {cleaned}")

        current = self.entries[idx]
        new_config = dict(current.config)
        if config is not None:
            new_config.update(dict(config))
        new_threshold = current.threshold if threshold is _UNSET else threshold
        new_enabled = current.enabled if enabled is None else enabled
        updated_entry = replace(
            current,
            enabled=new_enabled,
            threshold=new_threshold,
            config=new_config,
        )
        new_entries = _replace_at(self.entries, idx, updated_entry)
        return replace(self, entries=new_entries, updated_at=datetime.now(UTC))

    def append_entry(self, entry: MetricsPackEntry) -> MetricsPack:
        cleaned = entry.kind.strip()
        if not cleaned:
            raise ValueError("Metrics pack entry kind must not be empty")
        if not entry.removable:
            raise ValueError("custom metrics pack entries must have removable=True")
        if _index_of_kind(self.entries, cleaned) is not None:
            raise ValueError(f"metrics pack entry kind already exists: {cleaned}")
        normalized = replace(entry, kind=cleaned, config=dict(entry.config))
        return replace(
            self,
            entries=(*self.entries, normalized),
            updated_at=datetime.now(UTC),
        )

    def remove_entry(self, kind: str) -> MetricsPack:
        cleaned = kind.strip()
        if not cleaned:
            raise ValueError("Metrics pack entry kind must not be empty")
        idx = _index_of_kind(self.entries, cleaned)
        if idx is None:
            raise ValueError(f"unknown metrics pack entry kind: {cleaned}")
        target = self.entries[idx]
        if not target.removable:
            raise ValueError(f"metrics pack entry is not removable: {cleaned}")
        new_entries = self.entries[:idx] + self.entries[idx + 1 :]
        return replace(self, entries=new_entries, updated_at=datetime.now(UTC))


def _index_of_kind(entries: tuple[MetricsPackEntry, ...], kind: str) -> int | None:
    for i, entry in enumerate(entries):
        if entry.kind == kind:
            return i
    return None


def _replace_at(
    entries: tuple[MetricsPackEntry, ...],
    index: int,
    entry: MetricsPackEntry,
) -> tuple[MetricsPackEntry, ...]:
    return entries[:index] + (entry,) + entries[index + 1 :]
