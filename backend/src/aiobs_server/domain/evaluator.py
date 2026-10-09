from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

EVALUATOR_TYPES = frozenset({"deterministic", "llm_judge", "custom"})


@dataclass(frozen=True, slots=True)
class Evaluator:
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    type: str
    config: dict[str, Any]
    version: int

    @classmethod
    def create(
        cls,
        project_id: uuid.UUID,
        name: str,
        type: str,
        config: dict[str, Any],
        *,
        version: int = 1,
    ) -> Evaluator:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Evaluator name must not be empty")
        if type not in EVALUATOR_TYPES:
            raise ValueError(f"Evaluator type must be one of: {', '.join(sorted(EVALUATOR_TYPES))}")
        if version < 1:
            raise ValueError("Evaluator version must be >= 1")
        if "kind" not in config or not str(config["kind"]).strip():
            raise ValueError("Evaluator config must include a non-empty 'kind'")
        return cls(
            id=uuid.uuid4(),
            project_id=project_id,
            name=cleaned,
            type=type,
            config=dict(config),
            version=version,
        )
