from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from opengrade._context import resolve_or_create_project
from opengrade._http import OpengradeAPIError
from opengrade.client import Client
from opengrade.experiment.dataset import _is_uuid
from opengrade.experiment.result import ExperimentResult
from opengrade.experiment.serialization import _digest
from opengrade.judges import LlmJudge
from opengrade.metrics import LocalMetric
from opengrade.models import ExperimentResponse

Metric = str | Mapping[str, Any] | LlmJudge | LocalMetric | Callable[..., Any]
TASK_FAILED_EXPLANATION = "task raised before producing an output"
_JUDGE_KEY = "_llm_judge"
_MISSING: Any = object()
MAX_REPEATS = 100  # server limit on repeats of one item
ALIAS_PREFIX = "alias:"


def alias_name(ref: str) -> str | None:
    if not ref.startswith(ALIAS_PREFIX):
        return None
    name = ref[len(ALIAS_PREFIX) :].strip()
    if not name:
        raise ValueError(f"empty alias name in {ref!r}")
    return name


def _resolve_project(
    project: str | None,
    client: Client,
    *,
    activate: bool,
) -> str:
    if project is None:
        return client._project(None)
    if _is_uuid(project):
        return project
    created = resolve_or_create_project(project, client, activate=activate)
    if created is None:
        raise ValueError(f"could not resolve project {project!r}: platform unreachable")
    return created.id


def _local_name(metric: LocalMetric) -> str:
    assert metric.name is not None  # filled by _split_metrics
    return metric.name


def _split_metrics(
    metrics: Sequence[Metric],
) -> tuple[list[dict[str, Any]], list[LocalMetric]]:
    server: list[dict[str, Any]] = []
    local: list[LocalMetric] = []
    for index, metric in enumerate(metrics):
        if isinstance(metric, str):
            server.append({"kind": metric.strip()})
        elif isinstance(metric, LlmJudge):
            server.append({"kind": metric.name.strip(), _JUDGE_KEY: metric})
        elif isinstance(metric, Mapping):
            if not metric.get("kind"):
                raise ValueError(f"metric dict needs a 'kind': {metric!r}")
            server.append(dict(metric))
        elif isinstance(metric, LocalMetric) or callable(metric):
            spec = metric if isinstance(metric, LocalMetric) else LocalMetric(fn=metric)
            name = spec.name or getattr(spec.fn, "__name__", "") or ""
            if not name or name == "<lambda>":
                name = f"metric_{index}"
            local.append(replace(spec, name=name, config=dict(spec.config)))
        else:
            raise TypeError(f"unsupported metric {metric!r}")
    kinds = [entry["kind"] for entry in server]
    if len(set(kinds)) != len(kinds):
        raise ValueError(f"duplicate metric kinds: {kinds}")
    names = [_local_name(m) for m in local]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate local metric names: {names}")
    return server, local


def _resolve_metrics_set(client: Client, project_id: str, requested: list[dict[str, Any]]) -> str:
    """Find or create a metrics set holding exactly ``requested`` (enabled).

    Thresholds/config default to the project's default set, so ``"hit_at_k"``
    behaves like it does in the UI.
    """
    sets = client.metrics_sets.list(project_id)
    defaults: dict[str, dict[str, Any]] = {}
    default_set = next((s for s in sets if s.is_project_default), None)
    if default_set is not None:
        for e in client.metrics_sets.get(default_set.id).entries:
            defaults[e.kind] = {"threshold": e.threshold, "config": dict(e.config)}

    entries: list[dict[str, Any]] = []
    for spec in requested:
        judge = spec.get(_JUDGE_KEY)
        if isinstance(judge, LlmJudge):
            evaluator = judge.register(client, project_id)
            entries.append(
                {
                    "kind": spec["kind"],
                    "enabled": True,
                    "threshold": judge.threshold,
                    "config": {},
                    "evaluator_id": evaluator.id,
                }
            )
            continue
        base = defaults.get(spec["kind"], {"threshold": None, "config": {}})
        entry = {"kind": spec["kind"], "enabled": True, **base}
        entry.update({k: v for k, v in spec.items() if k != "kind"})
        entries.append(entry)

    label = "+".join(e["kind"] for e in entries)[:150]
    name = f"sdk:{label}@{_digest(entries)[:8]}"
    named = client.metrics_sets.list(project_id, name=name)
    if named:
        return named[0].id
    try:
        created = client.metrics_sets.create(
            project_id,
            name=name,
            entries=entries,
            description="Created by opengrade.evaluate()",
        )
    except OpengradeAPIError as exc:
        if exc.status != 409:
            raise
        # Created concurrently by another process — use theirs.
        named = client.metrics_sets.list(project_id, name=name)
        if named:
            return named[0].id
        raise
    return created.id


def _resolve_baseline(
    client: Client,
    project_id: str,
    baseline: str | ExperimentResponse | ExperimentResult | None,
    *,
    dataset_id: str,
) -> str | None:
    if baseline is None:
        return None
    if isinstance(baseline, ExperimentResult):
        return baseline.id
    if isinstance(baseline, ExperimentResponse):
        return baseline.id
    if _is_uuid(baseline):
        return baseline
    alias = alias_name(baseline)
    if alias is not None:
        try:
            return client.experiments.get_alias(alias, project_id=project_id).experiment_id
        except OpengradeAPIError as exc:
            if exc.status != 404:
                raise
            raise ValueError(
                f"no experiment alias {alias!r} in project {project_id}; "
                "promote a baseline first (Client.experiments.set_alias)"
            ) from exc
    matches = client.experiments.list(project_id, name=baseline)
    if not matches:
        raise ValueError(f"no baseline experiment named {baseline!r} in project {project_id}")
    same_dataset = [e for e in matches if str(e.dataset_id) == dataset_id]
    pool = same_dataset or matches
    return max(pool, key=lambda e: str(e.created_at or "")).id


def _default_name(task: Callable[..., Any] | None) -> str:
    stem = getattr(task, "__name__", "") if task is not None else ""
    if not stem or stem == "<lambda>":
        stem = "experiment"
    return f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}"


def _resolve_git(git: bool | Mapping[str, Any]) -> dict[str, Any] | None:
    if git is True:
        from opengrade.experiment import detect_git

        return detect_git()
    if not git:
        return None
    return {k: v for k, v in dict(git).items() if v is not None} or None
