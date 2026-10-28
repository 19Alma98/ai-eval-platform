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
from typing import Any
from uuid import UUID

import httpx2
import uvicorn

from opengrade_server.config import get_settings

EVALUATE_KEY = "evaluate"
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
    init_tracing: bool = False
    judge_model: str | None = None
    judge_api_base: str | None = None
    judge_api_key_env: str | None = None
    backend_store_uri: str | None = None
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
    as_json: bool = False,
) -> EvaluateConfig:
    meta, block, policy = split_config(raw)
    judge = block.get("judge") or {}
    if judge is not None and not isinstance(judge, dict):
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
        init_tracing=bool(block.get("init") or False),
        judge_model=_as_opt_str(judge.get("model")),
        judge_api_base=_as_opt_str(judge.get("api_base")),
        judge_api_key_env=_as_opt_str(judge.get("api_key_env")),
        backend_store_uri=backend_store_uri or _as_opt_str(block.get("backend_store_uri")),
        policy=policy,
        as_json=as_json,
    )
    # Script may supply DATASET/METRICS later — defer full exam check until resolve_task.
    validate_evaluate_config(cfg, require_exam=not bool(cfg.script) or bool(cfg.from_experiment))
    return cfg


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
    return target  # type: ignore[return-value]


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
    return response.json()


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, default=str))
