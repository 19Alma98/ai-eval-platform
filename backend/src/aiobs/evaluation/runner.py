from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from aiobs.domain.dataset import DatasetItem
from aiobs.domain.evaluation import EvaluationResultRecord, EvaluationRun
from aiobs.domain.evaluator import Evaluator as EvaluatorEntity
from aiobs.evaluation.protocol import Evaluator
from aiobs.evaluation.registry import create_evaluator


def config_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _requires_actual(kind: str) -> bool:
    return kind not in {
        "latency",
        "token_usage",
        "cost",
        "tool_call_success",
        "hit_at_k",
    }


class EvaluationRunner:
    def __init__(
        self,
        *,
        max_concurrency: int = 8,
        resolve_evaluator: Callable[[EvaluatorEntity], Evaluator] | None = None,
    ) -> None:
        self._max_concurrency = max(1, max_concurrency)
        self._resolve = resolve_evaluator or (
            lambda entity: create_evaluator(str(entity.config["kind"]), entity.config)
        )

    async def run_evaluator(
        self,
        *,
        run: EvaluationRun,
        evaluator_entity: EvaluatorEntity,
        items: list[DatasetItem],
    ) -> tuple[EvaluationRun, list[EvaluationResultRecord]]:
        started = datetime.now(UTC)
        run = run.with_status("RUNNING", started_at=started)
        kind = str(evaluator_entity.config.get("kind", ""))
        impl = self._resolve(evaluator_entity)
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _one(item: DatasetItem) -> EvaluationResultRecord:
            async with semaphore:
                return await self._evaluate_item(run.id, impl, item, kind)

        results = list(await asyncio.gather(*[_one(item) for item in items]))
        finished = datetime.now(UTC)
        labels = {r.label for r in results}
        if "ERROR" in labels:
            status = "ERROR"
        elif results and labels <= {"SKIPPED"}:
            status = "SKIPPED"
        elif any(r.score == 0.0 for r in results if r.score is not None):
            status = "FAILED"
        else:
            status = "PASSED"

        meta = {
            **run.metadata,
            "evaluator_name": evaluator_entity.name,
            "evaluator_version": evaluator_entity.version,
            "evaluator_kind": kind,
            "config_hash": config_hash(evaluator_entity.config),
        }
        run = run.with_status(status, finished_at=finished, metadata=meta)
        return run, results

    async def _evaluate_item(
        self,
        run_id: UUID,
        impl: Evaluator,
        item: DatasetItem,
        kind: str,
    ) -> EvaluationResultRecord:
        from aiobs.evaluation.protocol import EvaluationSample

        sample = EvaluationSample(
            input=item.input,
            expected_output=item.expected_output,
            actual_output=item.actual_output,
            context=item.context,
            metadata=dict(item.metadata),
        )
        if _requires_actual(kind) and sample.actual_output is None:
            return EvaluationResultRecord.create(
                run_id,
                item.id,
                score=None,
                label="SKIPPED",
                explanation="actual_output is missing",
                duration_ms=0,
            )
        started = time.perf_counter()
        try:
            result = await impl.evaluate(sample)
        except Exception as exc:  # noqa: BLE001 — map evaluator failures to ERROR
            duration_ms = int((time.perf_counter() - started) * 1000)
            return EvaluationResultRecord.create(
                run_id,
                item.id,
                score=None,
                label="ERROR",
                explanation=str(exc),
                metadata={"error_type": type(exc).__name__},
                duration_ms=duration_ms,
            )
        duration_ms = int((time.perf_counter() - started) * 1000)
        return EvaluationResultRecord.create(
            run_id,
            item.id,
            score=result.score,
            label=result.label,
            explanation=result.explanation,
            metadata=dict(result.metadata),
            duration_ms=duration_ms,
        )
