from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

ALIAS_NAME_MAX_LENGTH = 200
NOTE_MAX_LENGTH = 2000


def clean_alias_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Alias name must not be empty")
    if len(cleaned) > ALIAS_NAME_MAX_LENGTH:
        raise ValueError(f"Alias name must be at most {ALIAS_NAME_MAX_LENGTH} characters")
    return cleaned


@dataclass(frozen=True, slots=True)
class ExperimentAlias:
    project_id: uuid.UUID
    name: str
    experiment_id: uuid.UUID
    updated_at: datetime

    @classmethod
    def create(
        cls,
        project_id: uuid.UUID,
        name: str,
        experiment_id: uuid.UUID,
    ) -> ExperimentAlias:
        return cls(
            project_id=project_id,
            name=clean_alias_name(name),
            experiment_id=experiment_id,
            updated_at=datetime.now(UTC),
        )


@dataclass(frozen=True, slots=True)
class ExperimentAliasEvent:
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    experiment_id: uuid.UUID
    previous_experiment_id: uuid.UUID | None
    note: str | None
    created_at: datetime

    @classmethod
    def create(
        cls,
        alias: ExperimentAlias,
        *,
        previous_experiment_id: uuid.UUID | None,
        note: str | None = None,
    ) -> ExperimentAliasEvent:
        cleaned_note = note.strip() if note else None
        if cleaned_note and len(cleaned_note) > NOTE_MAX_LENGTH:
            raise ValueError(f"Alias note must be at most {NOTE_MAX_LENGTH} characters")
        return cls(
            id=uuid.uuid4(),
            project_id=alias.project_id,
            name=alias.name,
            experiment_id=alias.experiment_id,
            previous_experiment_id=previous_experiment_id,
            note=cleaned_note or None,
            created_at=alias.updated_at,
        )
