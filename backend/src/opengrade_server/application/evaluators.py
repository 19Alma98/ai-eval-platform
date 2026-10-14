from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from aiobs_server.application.projects import ProjectNotFoundError
from aiobs_server.domain.evaluator import Evaluator
from aiobs_server.domain.repositories import EvaluatorRepository, ProjectRepository
from aiobs_server.evaluation.registry import get_evaluator_factory


class EvaluatorNotFoundError(Exception):
    def __init__(self, evaluator_id: uuid.UUID) -> None:
        self.evaluator_id = evaluator_id
        super().__init__(f"Evaluator not found: {evaluator_id}")


class EvaluatorConflictError(Exception):
    def __init__(self, name: str, version: int) -> None:
        self.name = name
        self.version = version
        super().__init__(f"Evaluator already exists: {name} v{version}")


class UnknownEvaluatorKindError(Exception):
    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(f"Unknown evaluator kind: {kind}")


@dataclass(frozen=True, slots=True)
class CreateEvaluatorCommand:
    project_id: uuid.UUID
    name: str
    type: str
    config: dict[str, Any]
    version: int = 1


class CreateEvaluator:
    def __init__(
        self,
        evaluators: EvaluatorRepository,
        projects: ProjectRepository,
    ) -> None:
        self._evaluators = evaluators
        self._projects = projects

    async def execute(self, command: CreateEvaluatorCommand) -> Evaluator:
        project = await self._projects.get_by_id(command.project_id)
        if project is None:
            raise ProjectNotFoundError(command.project_id)
        kind = str(command.config.get("kind", ""))
        try:
            get_evaluator_factory(kind)
        except KeyError as exc:
            raise UnknownEvaluatorKindError(kind) from exc

        # Validate config by instantiating
        factory = get_evaluator_factory(kind)
        factory(command.config)

        evaluator = Evaluator.create(
            command.project_id,
            command.name,
            command.type,
            command.config,
            version=command.version,
        )
        try:
            return await self._evaluators.add(evaluator)
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise EvaluatorConflictError(evaluator.name, evaluator.version) from exc
            raise


class ListEvaluators:
    def __init__(self, evaluators: EvaluatorRepository) -> None:
        self._evaluators = evaluators

    async def execute(self, project_id: uuid.UUID) -> list[Evaluator]:
        return await self._evaluators.list_by_project(project_id)
