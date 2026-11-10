from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from opengrade._git import version_from_git
from opengrade.client import Client
from opengrade.experiment.dataset import DatasetLike, _resolve_dataset
from opengrade.experiment.result import ExperimentResult
from opengrade.experiment.runtime import ACTIVE_EXPERIMENT, Experiment
from opengrade.experiment.serialization import _jsonable
from opengrade.experiment.setup import (
    MAX_REPEATS,
    Metric,
    _default_name,
    _resolve_baseline,
    _resolve_git,
    _resolve_metrics_set,
    _resolve_project,
    _split_metrics,
)
from opengrade.metrics import LocalMetric
from opengrade.models import DatasetItemResponse, ExperimentResponse

logger = logging.getLogger("opengrade")


def _active_experiment() -> Experiment:
    exp = ACTIVE_EXPERIMENT.get()
    if exp is None:
        raise RuntimeError(
            "no active experiment: call inside `with opengrade.start_experiment(...)` "
            "or inside an item run (exp.run, run_task or an evaluate() task)"
        )
    return exp


def log_params(**params: Any) -> dict[str, Any]:
    """``Experiment.log_params`` on the active experiment."""
    return _active_experiment().log_params(**params)


def log_metrics(metrics: Mapping[str, float]) -> dict[str, float]:
    """``Experiment.log_metrics`` on the active experiment."""
    return _active_experiment().log_metrics(metrics)


def start_experiment(
    name: str | None = None,
    *,
    dataset: DatasetLike,
    metrics: Sequence[Metric] | None = None,
    metrics_set_id: str | None = None,
    params: Mapping[str, Any] | None = None,
    baseline: str | ExperimentResponse | ExperimentResult | None = None,
    project: str | None = None,
    version: str | None = None,
    git: bool | Mapping[str, Any] = True,
    task_type: str = "rag_qa",
    app_config_id: str | None = None,
    app_config_alias: str | None = None,
    repeats: int = 1,
    group_by: str | None = None,
    og: Any = None,
    client: Client | None = None,
) -> Experiment:
    """Create an experiment and return it for a manual loop.

    ``metrics=None`` scores with the project's default metrics set; a list scores
    with exactly those server kinds (plus local callables). Pass ``metrics_set_id``
    to reuse an existing set (e.g. cloned from another experiment) instead of
    resolving kinds. ``baseline`` is an experiment id, ``"alias:<name>"`` (the
    experiment a promoted alias points to), a name (latest wins) or a previous
    result. With an app config the server snapshots it as the experiment's params
    (``exp.params``), replacing ``params``.

    ``git=True`` records the commit the code runs at (local checkout, else CI env),
    so a compare shows which revisions candidate and baseline came from; it also
    becomes ``version`` (short SHA) when none is given. Pass a dict to set it
    explicitly, or ``False`` to skip.

    ``repeats`` runs every item that many times in ``run_task`` (pass ``repeat=`` to
    ``exp.run`` in a manual loop). Scores average per item, so the comparison with the
    baseline still pairs items, and items whose verdict changes between repeats are
    counted as flaky.

    ``group_by`` names a dataset-item metadata field (``"category"``, ``"meta.lang"``):
    the result then also reports means and baseline deltas per group value.
    """
    if not 1 <= repeats <= MAX_REPEATS:
        raise ValueError(f"repeats must be between 1 and {MAX_REPEATS}")
    explicit_client = client is not None
    if client is None and og is not None:
        client = og.client
    if client is None:
        from opengrade._opengrade import current

        client = current().client
    project_id = _resolve_project(project, client, activate=not explicit_client)
    dataset_id = _resolve_dataset(client, project_id, dataset, task_type=task_type)

    server_metrics: list[dict[str, Any]] = []
    local_metrics: list[LocalMetric] = []
    if metrics is not None:
        server_metrics, local_metrics = _split_metrics(metrics)
    if metrics_set_id is not None:
        if server_metrics:
            raise ValueError("pass metrics kinds or metrics_set_id, not both")
        resolved_metrics_set_id: str | None = metrics_set_id
        score_on_server = True
    else:
        resolved_metrics_set_id = (
            _resolve_metrics_set(client, project_id, server_metrics) if server_metrics else None
        )
        score_on_server = metrics is None or bool(server_metrics)
    baseline_id = _resolve_baseline(client, project_id, baseline, dataset_id=dataset_id)
    git_info = _resolve_git(git)
    if version is None:
        version = version_from_git(git_info)

    experiment = client.experiments.create(
        project_id,
        name=name or _default_name(None),
        dataset_id=dataset_id,
        model_config=_jsonable(dict(params or {})),
        version=version,
        git=git_info,
        baseline_experiment_id=baseline_id,
        app_config_id=app_config_id,
        app_config_alias=app_config_alias,
        metrics_set_id=resolved_metrics_set_id,
    )
    items = client.datasets.get(dataset_id).items
    if not items:
        raise ValueError(f"dataset {dataset_id} has no items")
    exp = Experiment(
        client=client,
        experiment=experiment,
        items=items,
        metrics_set_id=resolved_metrics_set_id,
        score_on_server=score_on_server,
        local_metrics=local_metrics,
        baseline_id=baseline_id,
        repeats=repeats,
        group_by=group_by,
    )
    logger.info("opengrade experiment %s started: %s", experiment.name, exp.url)
    return exp


def evaluate(
    *,
    dataset: DatasetLike,
    task: Callable[[DatasetItemResponse], Any],
    metrics: Sequence[Metric] | None = None,
    metrics_set_id: str | None = None,
    name: str | None = None,
    params: Mapping[str, Any] | None = None,
    baseline: str | ExperimentResponse | ExperimentResult | None = None,
    max_concurrency: int = 1,
    project: str | None = None,
    version: str | None = None,
    git: bool | Mapping[str, Any] = True,
    task_type: str = "rag_qa",
    app_config_id: str | None = None,
    app_config_alias: str | None = None,
    raise_on_error: bool = False,
    timeout: float = 600.0,
    repeats: int = 1,
    group_by: str | None = None,
    og: Any = None,
    client: Client | None = None,
) -> ExperimentResult:
    """Run ``task`` on every dataset item, score it and return the result.

    ``task(item)`` gets a ``DatasetItemResponse`` (``item.input``,
    ``item.expected_output``, ``item.metadata``) and returns the output. Calls to
    ``opengrade.set_retrieval_documents`` inside it feed retrieval metrics. A task that
    raises is recorded as an item error (unless ``raise_on_error``).

    ``repeats`` runs the task that many times per item, to measure non-deterministic
    pipelines: scores are averaged per item and flaky items are reported. ``group_by``
    (an item metadata field) adds per-group means and baseline deltas to the result.
    """
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be >= 1")
    exp = start_experiment(
        name or _default_name(task),
        dataset=dataset,
        metrics=metrics,
        metrics_set_id=metrics_set_id,
        params=params,
        baseline=baseline,
        project=project,
        version=version,
        git=git,
        task_type=task_type,
        app_config_id=app_config_id,
        app_config_alias=app_config_alias,
        repeats=repeats,
        group_by=group_by,
        og=og,
        client=client,
    )
    exp.run_task(task, max_concurrency=max_concurrency, raise_on_error=raise_on_error)
    result = exp.finish(timeout=timeout)
    logger.info("opengrade experiment %s finished: %s", result.experiment.name, result.url)
    return result
