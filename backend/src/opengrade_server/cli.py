"""Console entry point: ``opengrade ui`` and ``opengrade check``."""

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
        "experiment_id",
        "baseline_experiment_id",
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
    """AI Evaluation & Observability Platform CLI."""


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
    meta = {k: v for k, v in raw.items() if k in META_KEYS}
    policy = {k: v for k, v in raw.items() if k not in META_KEYS}
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
        resolved_project = resolve_str(project_id, meta, "project_id")
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

        project_uuid = _parse_uuid(resolved_project, "project_id")
        experiment_uuid = _parse_uuid(resolved_experiment, "experiment_id")
        payload: dict[str, Any] = {
            "experiment_id": str(experiment_uuid),
            "policy": policy_body,
        }
        if resolved_baseline:
            payload["baseline_experiment_id"] = str(
                _parse_uuid(resolved_baseline, "baseline_experiment_id")
            )

        url = f"{resolved_base.rstrip('/')}/api/v1/projects/{project_uuid}/release-check"
        try:
            response = httpx2.post(url, json=payload, timeout=60.0)
        except httpx2.HTTPError as exc:
            console.print(f"[red]Infrastructure error:[/red] {exc}")
            raise typer.Exit(EXIT_INFRA) from exc

        if response.status_code >= 500:
            console.print(f"[red]Infrastructure error:[/red] HTTP {response.status_code}")
            console.print(response.text)
            raise typer.Exit(EXIT_INFRA)
        if response.status_code >= 400:
            console.print(f"[red]Configuration/API error:[/red] HTTP {response.status_code}")
            console.print(response.text)
            raise typer.Exit(EXIT_CONFIG)

        body = response.json()
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


if __name__ == "__main__":
    app()
