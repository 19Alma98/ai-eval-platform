from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from aiobs.domain.dataset import DatasetItem
from aiobs.domain.evaluation import EvaluationResultRecord, EvaluationRun
from aiobs.domain.evaluator import Evaluator as EvaluatorEntity
from aiobs.evaluation.outcomes import item_verdict
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


def effective_entity(
    entity: EvaluatorEntity, config_override: dict[str, Any] | None
) -> EvaluatorEntity:
    """Overlay per-scoring config (e.g. a metrics set entry) on the evaluator config.

    ``kind`` is never overridable: it selects the implementation.
    """
    if not config_override:
        return entity
    config = {**entity.config, **config_override}
    if "kind" in entity.config:
        config["kind"] = entity.config["kind"]
    else:
        config.pop("kind", None)
    return replace(entity, config=config)


MISSING_OUTPUT_EXPLANATION = "no output recorded for this item in experiment"


def _apply_verdict(
    record: EvaluationResultRecord, pass_threshold: float | None
) -> EvaluationResultRecord:
    """Store the effective verdict as the label so pass_rate matches the run status.

    The evaluator's own label is kept in ``metadata.judge_label`` when it differs.
    """
    verdict = item_verdict(record.score, record.label, pass_threshold)
    if verdict is None or verdict == record.label:
        return record
    metadata = dict(record.metadata)
    if record.label is not None:
        metadata["judge_label"] = record.label
    return replace(record, label=verdict, metadata=metadata)


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
        pass_threshold: float | None = None,
        config_override: dict[str, Any] | None = None,
        missing_output_item_ids: set[UUID] | frozenset[UUID] = frozenset(),
    ) -> tuple[EvaluationRun, list[EvaluationResultRecord]]:
        started = datetime.now(UTC)
        run = run.with_status("RUNNING", started_at=started)
        evaluator_entity = effective_entity(evaluator_entity, config_override)
        kind = str(evaluator_entity.config.get("kind", ""))
        impl = self._resolve(evaluator_entity)
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _one(item: DatasetItem) -> EvaluationResultRecord:
            if item.id in missing_output_item_ids:
                # The app produced nothing for this item: a quality failure, not a
                # non-applicable metric, so it must not become SKIPPED.
                return EvaluationResultRecord.create(
                    run.id,
                    item.id,
                    score=0.0,
                    label="FAIL",
                    explanation=MISSING_OUTPUT_EXPLANATION,
                    metadata={"missing_output": True},
                    duration_ms=0,
                )
            async with semaphore:
                return await self._evaluate_item(run.id, impl, item, kind)

        results = [
            _apply_verdict(r, pass_threshold)
            for r in await asyncio.gather(*[_one(item) for item in items])
        ]
        finished = datetime.now(UTC)
        labels = {(r.label or "").strip().upper() for r in results}
        if "ERROR" in labels:
            status = "ERROR"
        elif results and labels <= {"SKIPPED"}:
            status = "SKIPPED"
        elif "FAIL" in labels:
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
        if config_override:
            meta["config_override"] = {k: v for k, v in config_override.items() if k != "kind"}
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
