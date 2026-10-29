"""Console entry point: ``opengrade ui``, ``opengrade check``, ``opengrade evaluate``."""

from __future__ import annotations

import os
import socket
import webbrowser
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import httpx2
import typer
import uvicorn
import yaml
from rich.console import Console
from rich.table import Table

from opengrade_server.cli_evaluate import (
    EVALUATE_KEY,
    RESERVED_TOP_LEVEL,
    AliasTarget,
    EmbeddedServer,
    EvaluateConfigError,
    alias_ref,
    apply_judge_env,
    emit_json,
    fetch_alias,
    post_release_check,
    resolve_evaluate_config,
    resolve_task,
    same_exam,
    without_regression,
)
from opengrade_server.config import DEFAULT_SQLITE_URL, Settings, get_settings
from opengrade_server.ui import ui_root

EXIT_PASS = 0
EXIT_GATE_FAILED = 1
EXIT_CONFIG = 2
EXIT_INFRA = 3

META_KEYS = frozenset(
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

PACKAGED_UI_HINT = (
    "Build it with `python scripts/package_ui.py` "
    "(or `./scripts/package-ui.sh`), or install a release wheel that includes the UI."
)

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


@app.callback()
def _root() -> None:
    """OpenGrade CLI."""


class PortInUseError(Exception):
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        super().__init__(f"port {port} on {host} is already in use")


def assert_port_available(host: str, port: int, *, timeout: float = 0.3) -> None:
    """Fail if something already accepts connections on host:port.

    A connect probe catches the case where another process (e.g. Docker) listens
    on 0.0.0.0 while we would bind 127.0.0.1 — browsers to localhost hit the
    other server even if a second bind might succeed.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        return
    raise PortInUseError(host, port)


def ui_config_warnings(settings: Settings) -> list[str]:
    """Return non-fatal startup warnings for common local misconfigurations."""
    warnings: list[str] = []
    api_base = settings.llm_api_base or ""
    if "host.docker.internal" in api_base:
        warnings.append(
            "LLM_API_BASE uses host.docker.internal (for containers). "
            "On the host, use http://localhost:11434 (or your local API URL)."
        )
    needs_key = not settings.llm_api_key and (
        settings.llm_model.startswith("gemini/")
        or (not api_base and not settings.llm_model.startswith("ollama/"))
    )
    if needs_key:
        warnings.append(
            f"Judge model is {settings.llm_model} but LLM_API_KEY is unset. "
            "Set LLM_API_KEY, or point LLM_MODEL / LLM_API_BASE at a local provider "
            "(e.g. ollama/… + http://localhost:11434)."
        )
    return warnings


def print_ui_startup_banner(uri: str, settings: Settings) -> None:
    if uri.startswith("sqlite"):
        console.print(f"Using SQLite backend store: [cyan]{uri}[/cyan]")
    else:
        console.print(f"Using backend store: [cyan]{uri}[/cyan]")

    env_path = Path.cwd() / ".env"
    if env_path.is_file():
        console.print(f"Loaded .env from [cyan]{env_path}[/cyan]")

    key_status = "set" if settings.llm_api_key else "unset"
    api_base = settings.llm_api_base or "(none)"
    console.print(
        f"LLM judge: model=[cyan]{settings.llm_model}[/cyan] "
        f"api_key=[cyan]{key_status}[/cyan] "
        f"api_base=[cyan]{api_base}[/cyan]"
    )
    if settings.content_capture_enabled:
        console.print(
            "Content capture: [cyan]on[/cyan] (span inputs/outputs, prompts, completions and "
            "document text are stored; CONTENT_CAPTURE_ENABLED=false to redact)"
        )
    else:
        console.print(
            "Content capture: [yellow]off[/yellow] (span text is redacted; live traffic "
            "is not scored)"
        )

    for message in ui_config_warnings(settings):
        console.print(f"[yellow]Warning:[/yellow] {message}")


def load_policy_file(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise typer.BadParameter(f"cannot read policy file: {exc}") from exc
    except yaml.YAMLError as exc:
        raise typer.BadParameter(f"invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise typer.BadParameter("policy file must be a YAML mapping")
    return raw


def split_meta(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split meta/evaluate reserved keys from policy rule blocks.

    ``evaluate`` is stripped so ``opengrade check`` ignores it when sharing YAML
    with ``opengrade evaluate``.
    """
    meta = {k: v for k, v in raw.items() if k in META_KEYS and k != EVALUATE_KEY}
    policy = {k: v for k, v in raw.items() if k not in RESERVED_TOP_LEVEL}
    return meta, policy


def resolve_str(flag: str | None, meta: dict[str, Any], *keys: str) -> str | None:
    if flag:
        return flag
    for key in keys:
        value = meta.get(key)
        if value is not None:
            return str(value)
    return None


def _parse_uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise typer.BadParameter(f"invalid {label}: {value}") from exc


@app.command("ui")
def ui(
    host: Annotated[str, typer.Option("--host", help="Bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port")] = 8000,
    backend_store_uri: Annotated[
        str | None,
        typer.Option(
            "--backend-store-uri",
            help="SQLAlchemy async DB URL (default: local SQLite ./opengrade.db)",
        ),
    ] = None,
    reload: Annotated[bool, typer.Option("--reload", help="Auto-reload (dev)")] = False,
    open_browser: Annotated[
        bool, typer.Option("--open/--no-open", help="Open the UI in a browser")
    ] = False,
) -> None:
    """Start the local API + packaged UI."""
    uri = backend_store_uri or os.environ.get("DATABASE_URL") or DEFAULT_SQLITE_URL
    os.environ["DATABASE_URL"] = uri
    get_settings.cache_clear()

    if ui_root() is None:
        console.print(f"[red]Packaged UI not found.[/red] {PACKAGED_UI_HINT}")
        raise typer.Exit(EXIT_CONFIG)

    try:
        assert_port_available(host, port)
    except PortInUseError:
        console.print(
            f"[red]Port {port} on {host} is already in use.[/red] "
            "Stop the other process or pass --port."
        )
        raise typer.Exit(EXIT_CONFIG) from None

    settings = get_settings()
    print_ui_startup_banner(uri, settings)

    url = f"http://{host}:{port}"
    console.print(f"AI Eval UI: [green]{url}[/green]  (API + OTLP on the same origin)")
    if open_browser:
        webbrowser.open(url)

    if reload:
        uvicorn.run(
            "opengrade_server.main:app",
            host=host,
            port=port,
            reload=True,
            log_level="info",
        )
    else:
        # Match container entrypoint: trust proxy headers; allow scoring drain.
        uvicorn.run(
            "opengrade_server.main:app",
            host=host,
            port=port,
            reload=False,
            log_level="info",
            proxy_headers=True,
            forwarded_allow_ips=settings.forwarded_allow_ips,
            timeout_graceful_shutdown=settings.shutdown_grace_seconds,
        )


@app.command("check")
def check(
    policy: Annotated[
        Path,
        typer.Option(..., "--policy", exists=True, dir_okay=False, readable=True),
    ],
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
    project_id: Annotated[str | None, typer.Option("--project-id")] = None,
    experiment_id: Annotated[str | None, typer.Option("--experiment-id")] = None,
    baseline_experiment_id: Annotated[str | None, typer.Option("--baseline-experiment-id")] = None,
) -> None:
    """Evaluate a release policy against an experiment via the API."""
    try:
        raw = load_policy_file(policy)
        meta, policy_body = split_meta(raw)
        resolved_base = resolve_str(base_url, meta, "api_base_url", "base_url")
        resolved_project = resolve_str(project_id, meta, "project_id", "project")
        resolved_experiment = resolve_str(experiment_id, meta, "experiment_id")
        resolved_baseline = resolve_str(baseline_experiment_id, meta, "baseline_experiment_id")

        if not resolved_base:
            raise typer.BadParameter("api base URL required (--base-url or api_base_url)")
        if not resolved_project:
            raise typer.BadParameter("project_id required (--project-id or project_id)")
        if not resolved_experiment:
            raise typer.BadParameter("experiment_id required (--experiment-id or experiment_id)")
        if not policy_body:
            raise typer.BadParameter("policy file has no rule blocks")

        # project must be a UUID for release-check URL (slug not accepted here)
        project_uuid = str(_parse_uuid(resolved_project, "project_id"))
        experiment_uuid = str(_parse_uuid(resolved_experiment, "experiment_id"))
        baseline_uuid = (
            str(_parse_uuid(resolved_baseline, "baseline_experiment_id"))
            if resolved_baseline
            else None
        )
        try:
            body = post_release_check(
                base_url=resolved_base,
                project_id=project_uuid,
                experiment_id=experiment_uuid,
                policy=policy_body,
                baseline_experiment_id=baseline_uuid,
            )
        except EvaluateConfigError as exc:
            console.print(f"[red]Configuration/API error:[/red] {exc}")
            raise typer.Exit(EXIT_CONFIG) from exc
        except httpx2.HTTPError as exc:
            console.print(f"[red]Infrastructure error:[/red] {exc}")
            raise typer.Exit(EXIT_INFRA) from exc
        except RuntimeError as exc:
            console.print(f"[red]Infrastructure error:[/red] {exc}")
            raise typer.Exit(EXIT_INFRA) from exc

        _print_checks(body)
        if body.get("status") == "passed":
            console.print("[green]Result: PASSED[/green]")
            raise typer.Exit(EXIT_PASS)
        console.print("[red]Result: FAILED[/red]")
        raise typer.Exit(EXIT_GATE_FAILED)
    except typer.BadParameter as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(EXIT_CONFIG) from exc
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]Unexpected error:[/red] {exc}")
        raise typer.Exit(EXIT_INFRA) from exc


def _print_checks(body: dict[str, Any]) -> None:
    table = Table(title="Quality gate checks")
    table.add_column("Metric")
    table.add_column("Actual")
    table.add_column("Threshold")
    table.add_column("Status")
    for check in body.get("checks", []):
        table.add_row(
            str(check.get("metric", "")),
            "n/a" if check.get("actual") is None else str(check.get("actual")),
            "n/a" if check.get("threshold") is None else str(check.get("threshold")),
            str(check.get("status", "")),
        )
    console.print(table)


def _promote(
    client: Any,
    *,
    project_id: str,
    alias: str,
    experiment_id: str,
    dataset_id: str | None,
    metrics_set_id: str | None,
    version: str | None,
    quiet: bool,
) -> dict[str, Any]:
    current = fetch_alias(client, project_id, alias)
    exam_changed = current is not None and not same_exam(current, dataset_id, metrics_set_id)
    note = f"opengrade evaluate: gate passed (version {version or 'n/a'})"
    if exam_changed:
        note += "; exam changed (new dataset / metrics set)"
    response = client.experiments.set_alias(
        alias, experiment_id, project_id=project_id, note=note, force=exam_changed
    )
    previous = response.previous_experiment_id
    if not quiet:
        console.print(
            f"[green]Promoted:[/green] alias {alias!r} → {experiment_id}"
            + (f" (was {previous})" if previous and previous != experiment_id else "")
        )
    return {
        "alias": alias,
        "experiment_id": experiment_id,
        "previous_experiment_id": previous,
        "exam_changed": exam_changed,
    }


@app.command("evaluate")
def evaluate_cmd(
    config: Annotated[
        Path | None,
        typer.Option("--config", exists=True, dir_okay=False, readable=True),
    ] = None,
    policy: Annotated[
        Path | None,
        typer.Option(
            "--policy",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Alias for --config (same YAML: evaluate + policy)",
        ),
    ] = None,
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
    project: Annotated[str | None, typer.Option("--project")] = None,
    task: Annotated[str | None, typer.Option("--task", help="module.path:callable")] = None,
    script: Annotated[
        Path | None,
        typer.Option("--script", exists=True, dir_okay=False, readable=True),
    ] = None,
    dataset: Annotated[str | None, typer.Option("--dataset")] = None,
    metrics: Annotated[
        str | None,
        typer.Option("--metrics", help="Comma-separated metric kinds"),
    ] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    baseline: Annotated[str | None, typer.Option("--baseline")] = None,
    from_experiment: Annotated[
        str | None,
        typer.Option("--from-experiment", help="Clone dataset + metrics_set from experiment"),
    ] = None,
    backend_store_uri: Annotated[
        str | None,
        typer.Option("--backend-store-uri", help="Embedded DB URL (default: temp SQLite)"),
    ] = None,
    version: Annotated[
        str | None,
        typer.Option("--version", help="Application version stored on the experiment (git SHA)"),
    ] = None,
    promote: Annotated[
        str | None,
        typer.Option(
            "--promote",
            help="Move this experiment alias (e.g. main) to the run when the gate passes",
        ),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON")] = False,
) -> None:
    """Run a dataset exam (evaluate) and optionally apply a release policy gate."""
    config_path = config or policy
    if config_path is None:
        console.print("[red]Configuration error:[/red] --config or --policy is required")
        raise typer.Exit(EXIT_CONFIG)

    embedded: EmbeddedServer | None = None
    try:
        raw = load_policy_file(config_path)
        cfg = resolve_evaluate_config(
            raw,
            base_url=base_url,
            project=project,
            task=task,
            script=script,
            dataset=dataset,
            metrics=metrics,
            name=name,
            baseline=baseline,
            from_experiment=from_experiment,
            backend_store_uri=backend_store_uri,
            version=version,
            promote=promote,
            as_json=as_json,
        )
        task_fn = resolve_task(cfg)

        tracking_uri = cfg.base_url
        if not tracking_uri:
            apply_judge_env(cfg)
            embedded = EmbeddedServer(database_url=cfg.backend_store_uri)
            tracking_uri = embedded.start()
            console.print(f"Embedded OpenGrade API: [cyan]{tracking_uri}[/cyan]")
        else:
            # Judge env still useful if the remote server reads the same process env (rare);
            # for remote, keys usually live on the server. Only apply when keys are set.
            if cfg.judge_model or cfg.judge_api_base or cfg.judge_api_key_env:
                apply_judge_env(cfg)

        import opengrade

        opengrade.set_tracking_uri(tracking_uri)
        project_name = cfg.project or "demo"
        project_resp = opengrade.set_project(project_name)
        if project_resp is None:
            raise RuntimeError(
                f"could not resolve or create project {project_name!r} at {tracking_uri}"
            )
        project_id = project_resp.id

        if cfg.init_tracing:
            opengrade.init(service_name=cfg.name or "opengrade-evaluate")

        client = opengrade.get_client()
        metrics_set_id: str | None = None
        dataset_arg: Any = cfg.dataset
        baseline_arg = cfg.baseline
        metrics_arg = cfg.metrics
        baseline_target: AliasTarget | None = None
        missing_baseline_alias: str | None = None

        from_experiment = cfg.from_experiment
        from_alias = alias_ref(from_experiment)
        if from_alias is not None:
            target = fetch_alias(client, project_id, from_alias)
            if target is None:
                raise EvaluateConfigError(
                    f"from_experiment alias {from_alias!r} is not set in project "
                    f"{project_name!r}: bootstrap it with dataset + metrics and --promote"
                )
            from_experiment = target.experiment_id
            if baseline_arg is None:
                baseline_target = target

        if from_experiment:
            template = client.experiments.get(from_experiment)
            if not template.dataset_id:
                raise EvaluateConfigError(f"from_experiment {from_experiment} has no dataset_id")
            if not template.metrics_set_id:
                raise EvaluateConfigError(
                    f"from_experiment {from_experiment} has no metrics_set_id"
                )
            dataset_arg = template.dataset_id
            metrics_set_id = template.metrics_set_id
            metrics_arg = None
            if baseline_arg is None:
                baseline_arg = from_experiment

        baseline_alias = alias_ref(baseline_arg)
        if baseline_alias is not None:
            baseline_target = fetch_alias(client, project_id, baseline_alias)
            if baseline_target is None:
                missing_baseline_alias = baseline_alias
                baseline_arg = None
                console.print(
                    f"[yellow]No baseline yet:[/yellow] alias {baseline_alias!r} is not set; "
                    "running without a baseline (regression checks skipped)"
                )
            else:
                baseline_arg = baseline_target.experiment_id

        assert dataset_arg is not None

        result = opengrade.evaluate(
            dataset=dataset_arg,
            task=task_fn,
            metrics=metrics_arg,
            metrics_set_id=metrics_set_id,
            name=cfg.name,
            params=cfg.params or None,
            baseline=baseline_arg,
            max_concurrency=cfg.max_concurrency,
            project=project_id,
            version=cfg.version,
            task_type=cfg.task_type,
            client=client,
        )

        run_dataset_id = result.experiment.dataset_id
        run_metrics_set_id = result.experiment.metrics_set_id
        gate_baseline_id = result.baseline_id
        if baseline_target is not None and not same_exam(
            baseline_target, run_dataset_id, run_metrics_set_id
        ):
            console.print(
                f"[yellow]Exam changed:[/yellow] alias {baseline_target.alias!r} ran another "
                "dataset / metrics set; regression checks skipped for this run"
            )
            gate_baseline_id = None

        payload: dict[str, Any] = {
            "experiment_id": result.id,
            "url": result.url,
            "project_id": project_id,
            "version": cfg.version,
            "baseline_id": gate_baseline_id,
            "metrics": result.metrics,
            "status": "evaluated",
        }
        if not cfg.as_json:
            console.print(result.summary())
            console.print(f"Experiment: [cyan]{result.url}[/cyan]")

        if not cfg.policy:
            payload["gate"] = None
            if cfg.as_json:
                emit_json(payload)
            raise typer.Exit(EXIT_PASS)

        gate_policy = cfg.policy
        alias_baseline = baseline_target is not None or missing_baseline_alias is not None
        if gate_baseline_id is None and alias_baseline:
            gate_policy = without_regression(cfg.policy)

        try:
            body = post_release_check(
                base_url=tracking_uri,
                project_id=project_id,
                experiment_id=result.id,
                policy=gate_policy,
                baseline_experiment_id=gate_baseline_id,
            )
        except EvaluateConfigError as exc:
            console.print(f"[red]Configuration/API error:[/red] {exc}")
            raise typer.Exit(EXIT_CONFIG) from exc
        except httpx2.HTTPError as exc:
            console.print(f"[red]Infrastructure error:[/red] {exc}")
            raise typer.Exit(EXIT_INFRA) from exc
        except RuntimeError as exc:
            console.print(f"[red]Infrastructure error:[/red] {exc}")
            raise typer.Exit(EXIT_INFRA) from exc

        passed = body.get("status") == "passed"
        payload["gate"] = body.get("status")
        payload["checks"] = body.get("checks")
        payload["promoted"] = None
        if passed and cfg.promote:
            payload["promoted"] = _promote(
                client,
                project_id=project_id,
                alias=cfg.promote,
                experiment_id=result.id,
                dataset_id=run_dataset_id,
                metrics_set_id=run_metrics_set_id,
                version=cfg.version,
                quiet=cfg.as_json,
            )
        if cfg.as_json:
            emit_json(payload)
        else:
            _print_checks(body)

        if passed:
            if not cfg.as_json:
                console.print("[green]Result: PASSED[/green]")
            raise typer.Exit(EXIT_PASS)
        if not cfg.as_json:
            if cfg.promote:
                console.print(f"Alias {cfg.promote!r} not moved: the gate failed")
            console.print("[red]Result: FAILED[/red]")
        raise typer.Exit(EXIT_GATE_FAILED)

    except EvaluateConfigError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(EXIT_CONFIG) from exc
    except typer.BadParameter as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(EXIT_CONFIG) from exc
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]Infrastructure error:[/red] {exc}")
        raise typer.Exit(EXIT_INFRA) from exc
    finally:
        if embedded is not None:
            embedded.stop()


if __name__ == "__main__":
    app()
