"""Experiment loop: datasets, runs, scoring, and evaluate()/start_experiment() API."""

from __future__ import annotations

from opengrade._git import detect_git, version_from_git
from opengrade.experiment.api import evaluate, log_metrics, log_params, start_experiment
from opengrade.experiment.dataset import (
    DatasetColumnError,
    DatasetLike,
    _inline_dataset_id,
    _resolve_dataset,
)
from opengrade.experiment.result import ExperimentResult, _fmt_delta
from opengrade.experiment.runtime import (
    ACTIVE_EXPERIMENT,
    Experiment,
    ItemRun,
    _auto_metrics,
    _output_entry,
)
from opengrade.experiment.serialization import _chunk_by_bytes, _jsonable
from opengrade.experiment.setup import (
    MAX_REPEATS,
    Metric,
    _default_name,
    _resolve_metrics_set,
    _resolve_project,
    _split_metrics,
)
from opengrade.metrics import LocalMetric

__all__ = [
    "_inline_dataset_id",
    "_fmt_delta",
    "_auto_metrics",
    "_output_entry",
    "_resolve_dataset",
    "_chunk_by_bytes",
    "_jsonable",
    "_default_name",
    "_resolve_metrics_set",
    "_resolve_project",
    "_split_metrics",
    "Experiment",
    "ExperimentResult",
    "ItemRun",
    "LocalMetric",
    "Metric",
    "DatasetColumnError",
    "DatasetLike",
    "ACTIVE_EXPERIMENT",
    "MAX_REPEATS",
    "evaluate",
    "log_metrics",
    "log_params",
    "start_experiment",
    "detect_git",
    "version_from_git",
]
