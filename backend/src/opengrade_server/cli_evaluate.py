"""Helpers for ``opengrade evaluate``: YAML resolve, task import, embedded API."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import socket
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx2
import uvicorn

from opengrade_server.config import get_settings
from opengrade_server.domain.experiment_output import MAX_REPEATS
from opengrade_server.regression.policy import (
    InvalidPolicyError,
    parse_release_policy,
    strip_baseline_rules,
)

EVALUATE_KEY = "evaluate"
ALIAS_PREFIX = "alias:"
RESERVED_TOP_LEVEL = frozenset(
    {
        "api_base_url",
        "base_url",
        "project_id",
        "project",
        "experiment_id",
        "baseline_experiment_id",
        EVALUATE_KEY,
    }
)


@dataclass
class EvaluateConfig:
    """Resolved evaluate settings (YAML + CLI flags)."""

    base_url: str | None
    project: str | None
    task_ref: str | None = None
    script: Path | None = None
    from_experiment: str | None = None
    dataset: str | None = None
    metrics: list[Any] | None = None
    name: str | None = None
    baseline: str | None = None
    task_type: str = "rag_qa"
    params: dict[str, Any] = field(default_factory=dict)
    max_concurrency: int = 1
    repeats: int = 1
    init_tracing: bool = False
    judge_model: str | None = None
    judge_api_base: str | None = None
    judge_api_key_env: str | None = None
    backend_store_uri: str | None = None
    version: str | None = None
    promote: str | None = None
    require_baseline: bool = False
    policy: dict[str, Any] = field(default_factory=dict)
    as_json: bool = False


class EvaluateConfigError(ValueError):
    """Invalid evaluate configuration (maps to CLI exit 2)."""


def split_config(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return (meta, evaluate_block, policy_body)."""
    meta = {k: v for k, v in raw.items() if k in RESERVED_TOP_LEVEL and k != EVALUATE_KEY}
    evaluate_block = raw.get(EVALUATE_KEY)
    if evaluate_block is None:
        evaluate_block = {}
    if not isinstance(evaluate_block, dict):
        raise EvaluateConfigError("'evaluate' must be a YAML mapping")
    policy = {k: v for k, v in raw.items() if k not in RESERVED_TOP_LEVEL}
    return meta, evaluate_block, policy


def _as_opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _merge_str(flag: str | None, *candidates: Any) -> str | None:
    if flag:
        return flag
    for value in candidates:
        resolved = _as_opt_str(value)
        if resolved is not None:
            return resolved
    return None


def _parse_metrics(raw: Any) -> list[Any] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return parts or None
    if isinstance(raw, list):
        return list(raw)
    raise EvaluateConfigError("metrics must be a list or comma-separated string")


def resolve_evaluate_config(
    raw: dict[str, Any],
    *,
    base_url: str | None = None,
    project: str | None = None,
    task: str | None = None,
    script: Path | None = None,
    dataset: str | None = None,
    metrics: str | None = None,
    name: str | None = None,
    baseline: str | None = None,
    from_experiment: str | None = None,
    backend_store_uri: str | None = None,
    version: str | None = None,
    promote: str | None = None,
    require_baseline: bool | None = None,
    as_json: bool = False,
) -> EvaluateConfig:
    meta, block, policy = split_config(raw)
    judge_raw = block.get("judge")
    if judge_raw is None:
        judge: dict[str, Any] = {}
    elif isinstance(judge_raw, dict):
        judge = cast(dict[str, Any], judge_raw)
    else:
        raise EvaluateConfigError("evaluate.judge must be a mapping")

    yaml_metrics = block.get("metrics")
    resolved_metrics = (
        _parse_metrics(metrics) if metrics is not None else _parse_metrics(yaml_metrics)
    )
    script_path = script
    if script_path is None and block.get("script") is not None:
        script_path = Path(str(block["script"]))
    cfg = EvaluateConfig(
        base_url=_merge_str(base_url, meta.get("api_base_url"), meta.get("base_url")),
        project=_merge_str(
            project, meta.get("project"), meta.get("project_id"), block.get("project")
        ),
        task_ref=_merge_str(task, block.get("task")),
        script=script_path,
        from_experiment=_merge_str(from_experiment, block.get("from_experiment")),
        dataset=_merge_str(dataset, block.get("dataset")),
        metrics=resolved_metrics,
        name=_merge_str(name, block.get("name")),
        baseline=_merge_str(baseline, block.get("baseline")),
        task_type=_as_opt_str(block.get("task_type")) or "rag_qa",
        params=dict(block.get("params") or {}),
        max_concurrency=int(block.get("max_concurrency") or 1),
        repeats=int(block.get("repeats") or 1),
        init_tracing=bool(block.get("init") or False),
        judge_model=_as_opt_str(judge.get("model")),
        judge_api_base=_as_opt_str(judge.get("api_base")),
        judge_api_key_env=_as_opt_str(judge.get("api_key_env")),
        backend_store_uri=backend_store_uri or _as_opt_str(block.get("backend_store_uri")),
        version=_merge_str(version, block.get("version")),
        promote=_merge_str(promote, block.get("promote")),
        require_baseline=(
            require_baseline
            if require_baseline is not None
            else _as_bool("require_baseline", block.get("require_baseline", False))
        ),
        policy=policy,
        as_json=as_json,
    )
    # Script may supply DATASET/METRICS later — defer full exam check until resolve_task.
    validate_evaluate_config(cfg, require_exam=not bool(cfg.script) or bool(cfg.from_experiment))
    return cfg


def _as_bool(label: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise EvaluateConfigError(f"evaluate.{label} must be true or false")
    return value


def policy_needs_baseline(policy: dict[str, Any]) -> bool:
    """True when the policy has rules that compare with a baseline. A malformed policy
    reports False here; the release-check call returns the real error."""
    try:
        return parse_release_policy(policy).needs_baseline()
    except InvalidPolicyError:
        return False


def validate_evaluate_config(cfg: EvaluateConfig, *, require_exam: bool = True) -> None:
    has_task = bool(cfg.task_ref)
    has_script = cfg.script is not None
    if has_task == has_script:
        raise EvaluateConfigError(
            "exactly one of evaluate.task / --task or evaluate.script / --script"
        )
    has_from = bool(cfg.from_experiment)
    has_boot = bool(cfg.dataset) and cfg.metrics is not None
    has_partial_boot = bool(cfg.dataset) ^ (cfg.metrics is not None)
    if has_from and (cfg.dataset or cfg.metrics is not None):
        raise EvaluateConfigError("from_experiment is XOR with dataset + metrics")
    if require_exam:
        if not has_from and not has_boot:
            if has_partial_boot:
                raise EvaluateConfigError("bootstrap requires both dataset and metrics")
            raise EvaluateConfigError(
                "exam definition required: from_experiment or dataset + metrics"
            )
    if cfg.max_concurrency < 1:
        raise EvaluateConfigError("max_concurrency must be >= 1")
    if not 1 <= cfg.repeats <= MAX_REPEATS:
        raise EvaluateConfigError(f"repeats must be between 1 and {MAX_REPEATS}")
    if cfg.promote and not cfg.policy:
        raise EvaluateConfigError("promote needs policy blocks: only a passing gate promotes")
    if cfg.require_baseline:
        if not cfg.baseline and not cfg.from_experiment:
            raise EvaluateConfigError(
                "require_baseline needs baseline (e.g. alias:main) or from_experiment"
            )
        if not policy_needs_baseline(cfg.policy):
            raise EvaluateConfigError(
                "require_baseline needs a policy rule that compares with the baseline "
                "(regression, groups.max_delta or a max_increase / max_decrease bound)"
            )
    if cfg.version is not None and len(cfg.version) > 200:
        raise EvaluateConfigError("version must be at most 200 characters")
    for label, ref in (("baseline", cfg.baseline), ("from_experiment", cfg.from_experiment)):
        if alias_ref(ref) == "":
            raise EvaluateConfigError(f"{label}: empty alias name in {ref!r}")


def apply_judge_env(cfg: EvaluateConfig) -> None:
    """Map evaluate.judge into process env for the embedded/remote server Settings."""
    if cfg.judge_model:
        os.environ["LLM_MODEL"] = cfg.judge_model
    if cfg.judge_api_base:
        os.environ["LLM_API_BASE"] = cfg.judge_api_base
    if cfg.judge_api_key_env:
        key = os.environ.get(cfg.judge_api_key_env)
        if not key:
            raise EvaluateConfigError(
                f"judge.api_key_env={cfg.judge_api_key_env!r} is unset in the environment"
            )
        os.environ["LLM_API_KEY"] = key
    get_settings.cache_clear()


def load_task_from_ref(ref: str) -> Callable[..., Any]:
    """Import ``module.path:attr`` (uvicorn-style)."""
    if ":" not in ref:
        raise EvaluateConfigError(f"task must be module.path:attr, got {ref!r}")
    module_name, _, attr = ref.partition(":")
    if not module_name or not attr:
        raise EvaluateConfigError(f"task must be module.path:attr, got {ref!r}")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise EvaluateConfigError(f"cannot import task module {module_name!r}: {exc}") from exc
    try:
        target = module
        for part in attr.split("."):
            target = getattr(target, part)
    except AttributeError as exc:
        raise EvaluateConfigError(f"task attribute {attr!r} not found on {module_name}") from exc
    if not callable(target):
        raise EvaluateConfigError(f"task {ref!r} is not callable")
    return cast(Callable[..., Any], target)


def load_task_from_script(path: Path) -> tuple[Callable[..., Any], dict[str, Any]]:
    """Load ``task`` (and optional DATASET/METRICS) from a Python file."""
    if not path.is_file():
        raise EvaluateConfigError(f"script not found: {path}")
    spec = importlib.util.spec_from_file_location(f"opengrade_eval_script_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise EvaluateConfigError(f"cannot load script: {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise EvaluateConfigError(f"script {path} failed to import: {exc}") from exc
    task = getattr(module, "task", None)
    if not callable(task):
        raise EvaluateConfigError(f"script {path} must define a callable task(item)")
    extras: dict[str, Any] = {}
    if getattr(module, "DATASET", None) is not None:
        extras["dataset"] = module.DATASET
    if getattr(module, "METRICS", None) is not None:
        extras["metrics"] = list(module.METRICS)
    return task, extras


def resolve_task(cfg: EvaluateConfig) -> Callable[..., Any]:
    if cfg.task_ref:
        validate_evaluate_config(cfg, require_exam=True)
        return load_task_from_ref(cfg.task_ref)
    assert cfg.script is not None
    task, extras = load_task_from_script(cfg.script)
    # Script DATASET/METRICS only fill bootstrap gaps (never override from_experiment).
    if not cfg.from_experiment:
        if cfg.dataset is None and "dataset" in extras:
            cfg.dataset = str(extras["dataset"])
        if cfg.metrics is None and "metrics" in extras:
            cfg.metrics = list(extras["metrics"])
    validate_evaluate_config(cfg, require_exam=True)
    return task


def pick_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


class EmbeddedServer:
    """Run FastAPI (no UI) in a background thread for the duration of evaluate."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int | None = None,
        database_url: str | None = None,
    ) -> None:
        self.host = host
        self.port = port or pick_free_port(host)
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        if database_url:
            self.database_url = database_url
        else:
            self._tmp = tempfile.TemporaryDirectory(prefix="opengrade-eval-")
            db_path = Path(self._tmp.name) / "opengrade.db"
            self.database_url = f"sqlite+aiosqlite:///{db_path}"
        self.base_url = f"http://{self.host}:{self.port}"
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self, *, ready_timeout: float = 60.0) -> str:
        os.environ["DATABASE_URL"] = self.database_url
        get_settings.cache_clear()

        from opengrade_server.main import create_app

        app = create_app(mount_packaged_ui=False)
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, name="opengrade-embedded", daemon=True
        )
        self._thread.start()
        deadline = time.monotonic() + ready_timeout
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            dead = (
                self._thread is not None
                and not self._thread.is_alive()
                and self._server.should_exit
            )
            if dead:
                raise RuntimeError("embedded OpenGrade server exited before becoming ready")
            try:
                response = httpx2.get(f"{self.base_url}/ready", timeout=1.0)
                if response.status_code == 200:
                    return self.base_url
            except httpx2.HTTPError as exc:
                last_err = exc
            time.sleep(0.1)
        raise RuntimeError(
            f"embedded OpenGrade server not ready within {ready_timeout}s: {last_err}"
        )

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=15.0)
            self._thread = None
        self._server = None
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None
        get_settings.cache_clear()


def post_release_check(
    *,
    base_url: str,
    project_id: str,
    experiment_id: str,
    policy: dict[str, Any],
    baseline_experiment_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "experiment_id": str(UUID(experiment_id)),
        "policy": policy,
    }
    if baseline_experiment_id:
        payload["baseline_experiment_id"] = str(UUID(baseline_experiment_id))
    url = f"{base_url.rstrip('/')}/api/v1/projects/{UUID(project_id)}/release-check"
    response = httpx2.post(url, json=payload, timeout=60.0)
    if response.status_code >= 500:
        raise RuntimeError(f"release-check HTTP {response.status_code}: {response.text}")
    if response.status_code >= 400:
        raise EvaluateConfigError(f"release-check HTTP {response.status_code}: {response.text}")
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError(f"release-check returned non-object JSON: {type(body).__name__}")
    return cast(dict[str, Any], body)


DEFAULT_SHOW_REGRESSIONS = 10


def fetch_regressed_items(
    *,
    base_url: str,
    experiment_id: str,
    baseline_id: str,
    evaluators: list[tuple[str, str]],
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """Test cases whose score dropped vs the baseline, merged across evaluators.

    ``evaluators`` is ``[(evaluator_id, name), …]``. Returns up to ``limit`` items (most
    regressed metrics first, then largest total drop) and the total number of regressed
    items. Each item: ``dataset_item_id``, ``input``, ``expected_output``,
    ``baseline_output``, ``candidate_output`` and ``metrics`` (per regressed evaluator:
    scores, labels, delta, candidate explanation).
    """
    by_item: dict[str, dict[str, Any]] = {}
    root = base_url.rstrip("/")
    for evaluator_id, name in evaluators:
        url = f"{root}/api/v1/experiments/{UUID(experiment_id)}/compare/{UUID(baseline_id)}/items"
        response = httpx2.get(
            url,
            params={"evaluator_id": str(UUID(evaluator_id)), "regressions_only": "true"},
            timeout=60.0,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"compare items HTTP {response.status_code}: {response.text}")
        for row in response.json().get("items", []):
            item_id = str(row["dataset_item_id"])
            baseline = row.get("baseline") or {}
            candidate = row.get("candidate") or {}
            item = by_item.setdefault(
                item_id,
                {
                    "dataset_item_id": item_id,
                    "input": row.get("input"),
                    "expected_output": row.get("expected_output"),
                    "baseline_output": baseline.get("actual_output"),
                    "candidate_output": candidate.get("actual_output"),
                    "metrics": [],
                },
            )
            item["metrics"].append(
                {
                    "metric": name,
                    "baseline_score": baseline.get("score"),
                    "candidate_score": candidate.get("score"),
                    "baseline_label": baseline.get("label"),
                    "candidate_label": candidate.get("label"),
                    "delta": row.get("delta"),
                    "explanation": candidate.get("explanation"),
                }
            )
    items = sorted(
        by_item.values(),
        key=lambda it: (
            -len(it["metrics"]),
            sum(m["delta"] or 0.0 for m in it["metrics"]),
            it["dataset_item_id"],
        ),
    )
    return items[:limit], len(items)


def alias_ref(ref: str | None) -> str | None:
    if ref is None or not ref.startswith(ALIAS_PREFIX):
        return None
    return ref[len(ALIAS_PREFIX) :].strip()


@dataclass(frozen=True)
class AliasTarget:
    alias: str
    experiment_id: str
    dataset_id: str | None
    metrics_set_id: str | None
    version: str | None


def fetch_alias(client: Any, project_id: str, alias: str) -> AliasTarget | None:
    from opengrade import OpengradeAPIError

    try:
        response = client.experiments.get_alias(alias, project_id=project_id)
    except OpengradeAPIError as exc:
        if exc.status == 404:
            return None
        raise
    return AliasTarget(
        alias=alias,
        experiment_id=str(response.experiment_id),
        dataset_id=response.experiment.dataset_id,
        metrics_set_id=response.experiment.metrics_set_id,
        version=response.experiment.version,
    )


def same_exam(target: AliasTarget, dataset_id: str | None, metrics_set_id: str | None) -> bool:
    return target.dataset_id == dataset_id and target.metrics_set_id == metrics_set_id


def without_baseline_rules(policy: dict[str, Any]) -> dict[str, Any]:
    """Policy for a run with no comparable baseline (see ``strip_baseline_rules``)."""
    return strip_baseline_rules(policy)


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, default=str))
