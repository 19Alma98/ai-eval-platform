from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

_UNSET: Any = object()


@dataclass(frozen=True, slots=True)
class MetricsSetEntry:
    id: uuid.UUID
    kind: str
    enabled: bool
    threshold: float | None
    config: dict[str, Any]
    evaluator_id: uuid.UUID | None
    is_default: bool
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _seed_entry(
    kind: str,
    *,
    enabled: bool,
    threshold: float | None,
    config: dict[str, Any],
) -> MetricsSetEntry:
    return MetricsSetEntry(
        id=uuid.uuid4(),
        kind=kind,
        enabled=enabled,
        threshold=threshold,
        config=dict(config),
        evaluator_id=None,
        is_default=True,
    )


DEFAULT_RAG_SET_ENTRIES: tuple[MetricsSetEntry, ...] = (
    _seed_entry("hit_at_k", enabled=True, threshold=0.8, config={"k": 5}),
    _seed_entry("recall_at_k", enabled=True, threshold=0.8, config={"k": 5}),
    _seed_entry("mrr", enabled=True, threshold=0.5, config={"k": 5}),
    _seed_entry("context_precision", enabled=True, threshold=0.7, config={}),
    _seed_entry("must_contain", enabled=True, threshold=1.0, config={"case_sensitive": False}),
    _seed_entry("groundedness", enabled=True, threshold=0.7, config={}),
    _seed_entry("correctness", enabled=True, threshold=0.7, config={}),
    _seed_entry("latency", enabled=True, threshold=None, config={"max_ms": 5000}),
)


@dataclass(frozen=True, slots=True)
class MetricsSet:
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    version: int
    description: str | None
    is_project_default: bool
    created_at: datetime
    updated_at: datetime
    entries: tuple[MetricsSetEntry, ...]

    @classmethod
    def create_project_default(cls, project_id: uuid.UUID) -> MetricsSet:
        now = datetime.now(UTC)
        entries = tuple(
            replace(e, id=uuid.uuid4(), config=dict(e.config), created_at=now)
            for e in DEFAULT_RAG_SET_ENTRIES
        )
        return cls(
            id=uuid.uuid4(),
            project_id=project_id,
            name="Default",
            version=1,
            description=None,
            is_project_default=True,
            created_at=now,
            updated_at=now,
            entries=entries,
        )

    @classmethod
    def create(
        cls,
        project_id: uuid.UUID,
        name: str,
        *,
        version: int = 1,
        description: str | None = None,
        entries: tuple[MetricsSetEntry, ...] = (),
    ) -> MetricsSet:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Metrics set name must not be empty")
        if version < 1:
            raise ValueError("Metrics set version must be >= 1")
        now = datetime.now(UTC)
        normalized = tuple(
            replace(
                e,
                kind=_clean_kind(e.kind),
                config=dict(e.config),
                is_default=False,
                created_at=e.created_at,
            )
            for e in entries
        )
        _assert_unique_kinds(normalized)
        assert_unique_evaluator_ids(normalized)
        return cls(
            id=uuid.uuid4(),
            project_id=project_id,
            name=cleaned,
            version=version,
            description=description.strip() if description else None,
            is_project_default=False,
            created_at=now,
            updated_at=now,
            entries=normalized,
        )

    def patch_entry(
        self,
        kind: str,
        *,
        enabled: bool | None = None,
        threshold: float | None | Any = _UNSET,
        config: dict[str, Any] | None = None,
        evaluator_id: uuid.UUID | None | Any = _UNSET,
    ) -> MetricsSet:
        cleaned = _clean_kind(kind)
        idx = _index_of_kind(self.entries, cleaned)
        if idx is None:
            raise ValueError(f"unknown metrics set entry kind: {cleaned}")
        current = self.entries[idx]
        new_config = dict(current.config)
        if config is not None:
            new_config.update(dict(config))
        updated_entry = replace(
            current,
            enabled=current.enabled if enabled is None else enabled,
            threshold=current.threshold if threshold is _UNSET else threshold,
            config=new_config,
            evaluator_id=current.evaluator_id if evaluator_id is _UNSET else evaluator_id,
        )
        return replace(
            self,
            entries=_replace_at(self.entries, idx, updated_entry),
            updated_at=datetime.now(UTC),
        )

    def append_entry(self, entry: MetricsSetEntry) -> MetricsSet:
        cleaned = _clean_kind(entry.kind)
        if _index_of_kind(self.entries, cleaned) is not None:
            raise ValueError(f"metrics set entry kind already exists: {cleaned}")
        normalized = replace(
            entry,
            kind=cleaned,
            config=dict(entry.config),
            is_default=False,
        )
        return replace(
            self,
            entries=(*self.entries, normalized),
            updated_at=datetime.now(UTC),
        )

    def remove_entry(self, kind: str) -> MetricsSet:
        cleaned = _clean_kind(kind)
        idx = _index_of_kind(self.entries, cleaned)
        if idx is None:
            raise ValueError(f"unknown metrics set entry kind: {cleaned}")
        target = self.entries[idx]
        if target.is_default:
            raise ValueError(f"metrics set entry is_default cannot be deleted: {cleaned}")
        new_entries = self.entries[:idx] + self.entries[idx + 1 :]
        return replace(self, entries=new_entries, updated_at=datetime.now(UTC))

    def remove_entry_by_id(self, entry_id: uuid.UUID) -> MetricsSet:
        idx = next((i for i, e in enumerate(self.entries) if e.id == entry_id), None)
        if idx is None:
            raise ValueError(f"unknown metrics set entry: {entry_id}")
        target = self.entries[idx]
        if target.is_default:
            raise ValueError(f"metrics set entry is_default cannot be deleted: {target.kind}")
        new_entries = self.entries[:idx] + self.entries[idx + 1 :]
        return replace(self, entries=new_entries, updated_at=datetime.now(UTC))

    def copy_as_next_version(self, next_version: int) -> MetricsSet:
        if next_version < 1:
            raise ValueError("Metrics set version must be >= 1")
        now = datetime.now(UTC)
        copied = tuple(
            replace(
                e,
                id=uuid.uuid4(),
                config=dict(e.config),
                is_default=False,
                created_at=now,
            )
            for e in self.entries
        )
        return replace(
            self,
            id=uuid.uuid4(),
            version=next_version,
            is_project_default=False,
            created_at=now,
            updated_at=now,
            entries=copied,
        )


def _clean_kind(kind: str) -> str:
    cleaned = kind.strip()
    if not cleaned:
        raise ValueError("Metrics set entry kind must not be empty")
    return cleaned


def _assert_unique_kinds(entries: tuple[MetricsSetEntry, ...]) -> None:
    kinds = [e.kind for e in entries]
    if len(set(kinds)) != len(kinds):
        raise ValueError("duplicate metrics set entry kinds")


def assert_unique_evaluator_ids(entries: tuple[MetricsSetEntry, ...]) -> None:
    """Each evaluator backs at most one entry.

    Thresholds and config overrides are keyed by evaluator at scoring time, and runs
    are compared per evaluator, so two entries sharing one evaluator would silently
    overwrite each other. A second config needs its own evaluator.
    """
    kinds_by_evaluator: dict[uuid.UUID, list[str]] = {}
    for entry in entries:
        if entry.evaluator_id is not None:
            kinds_by_evaluator.setdefault(entry.evaluator_id, []).append(entry.kind)
    shared = [kinds for kinds in kinds_by_evaluator.values() if len(kinds) > 1]
    if shared:
        raise ValueError(
            "evaluator_id is shared by metrics set entries: "
            + "; ".join(", ".join(kinds) for kinds in shared)
            + " (create a separate evaluator for each entry)"
        )


def _index_of_kind(entries: tuple[MetricsSetEntry, ...], kind: str) -> int | None:
    for i, entry in enumerate(entries):
        if entry.kind == kind:
            return i
    return None


def _replace_at(
    entries: tuple[MetricsSetEntry, ...],
    index: int,
    entry: MetricsSetEntry,
) -> tuple[MetricsSetEntry, ...]:
    return entries[:index] + (entry,) + entries[index + 1 :]
