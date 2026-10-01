from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import httpx
import typer
import yaml
from rich.console import Console
from rich.table import Table

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

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


@app.callback()
def _root() -> None:
    """AI Evaluation & Observability Platform CLI."""


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
            response = httpx.post(url, json=payload, timeout=60.0)
        except httpx.HTTPError as exc:
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
    table = Table(title="Release gate checks")
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
