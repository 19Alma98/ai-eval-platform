#!/usr/bin/env python3
"""Run the portfolio demo loop: People Ops assistant (MODEL1 vs MODEL2) → datasets → experiments → compare → aiobs check."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SDK_DIR = ROOT / "sdk"
APP_DIR = ROOT / "examples" / "hr_it_assistant"
POLICY_PATH = APP_DIR / "aiobs.yaml"
CLI_DIR = ROOT / "cli"


def http_json(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"content-type": "application/json", "accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} -> {exc.code}: {detail}") from exc


def ensure_project(base: str, slug: str, name: str) -> dict[str, Any]:
    projects = http_json("GET", f"{base}/api/v1/projects")
    for project in projects or []:
        if project.get("slug") == slug:
            print(f"reusing project {slug} ({project['id']})")
            return project
    project = http_json(
        "POST",
        f"{base}/api/v1/projects",
        body={"name": name, "slug": slug},
    )
    print(f"created project {slug} ({project['id']})")
    return project


def warn_content_capture(base: str) -> None:
    # Soft check: create a tiny OTLP probe is expensive; document and rely on env.
    print(
        "note: API must have CONTENT_CAPTURE_ENABLED=true "
        "(docker compose api service sets this; local .env may not)."
    )
    _ = base


def run_assistant(
    model: str, *, project_slug: str, env_extra: dict[str, str]
) -> list[dict[str, Any]]:
    cmd = [
        "uv",
        "run",
        "--extra",
        "openai",
        "--with",
        "openai",
        "python",
        str(APP_DIR / "main.py"),
        "--model",
        model,
        "--all",
        "--json",
    ]
    env = os.environ.copy()
    env.update(env_extra)
    env["AIOBS_PROJECT_SLUG"] = project_slug
    env["OLLAMA_MODEL"] = model
    print(f"running hr_it_assistant model={model} ...")
    proc = subprocess.run(
        cmd,
        cwd=str(SDK_DIR),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    if proc.stderr.strip():
        print(proc.stderr.strip(), file=sys.stderr)
    results: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        results.append(json.loads(line))
    if not results:
        raise RuntimeError(f"hr_it_assistant produced no results (model={model})")
    time.sleep(1.0)
    return results


def wait_for_trace(
    base: str, project_id: str, trace_id: str, *, attempts: int = 20
) -> dict[str, Any]:
    url = f"{base}/api/v1/projects/{project_id}/traces/{trace_id}"
    last_err: Exception | None = None
    for _ in range(attempts):
        try:
            detail = http_json("GET", url)
            if detail and (
                detail.get("input") is not None or detail.get("output") is not None
            ):
                return detail
            if detail:
                # Trace exists but content missing — still usable if we patch expected via results
                return detail
        except RuntimeError as exc:
            last_err = exc
        time.sleep(0.5)
    if last_err:
        raise RuntimeError(f"trace {trace_id} not found: {last_err}") from last_err
    raise RuntimeError(f"trace {trace_id} not found")


def create_dataset_from_runs(
    base: str,
    project_id: str,
    *,
    name: str,
    runs: list[dict[str, Any]],
) -> str:
    dataset = http_json(
        "POST",
        f"{base}/api/v1/projects/{project_id}/datasets",
        body={"name": name, "description": f"portfolio demo {name}", "task_type": "rag_qa"},
    )
    dataset_id = dataset["id"]
    for run in runs:
        detail = wait_for_trace(base, project_id, run["trace_id"])
        expected = run.get("expected_output")
        has_content = detail.get("output") is not None
        if has_content:
            http_json(
                "POST",
                f"{base}/api/v1/datasets/{dataset_id}/items/from-trace",
                body={
                    "trace_id": run["trace_id"],
                    "expected_output": expected,
                    "metadata": {
                        "model": run.get("model"),
                        "doc_ids": run.get("doc_ids"),
                    },
                },
            )
            print(f"  from-trace {run['trace_id'][:8]}… ok")
        else:
            http_json(
                "POST",
                f"{base}/api/v1/datasets/{dataset_id}/items",
                body={
                    "input": run["question"],
                    "expected_output": expected,
                    "actual_output": run["answer"],
                    "source_trace_id": run["trace_id"],
                    "metadata": {
                        "model": run.get("model"),
                        "doc_ids": run.get("doc_ids"),
                        "backfilled": True,
                    },
                },
            )
            print(
                f"  item+source_trace {run['trace_id'][:8]}… "
                "(trace had no captured output — enable CONTENT_CAPTURE_ENABLED)"
            )
    return dataset_id


def ensure_quality_evaluator(base: str, project_id: str) -> str:
    existing = http_json("GET", f"{base}/api/v1/projects/{project_id}/evaluators") or []
    for ev in existing:
        if ev.get("name") == "quality":
            print(f"reusing evaluator quality ({ev['id']})")
            return ev["id"]
    ev = http_json(
        "POST",
        f"{base}/api/v1/projects/{project_id}/evaluators",
        body={
            "name": "quality",
            "type": "deterministic",
            "config": {"kind": "contains", "case_sensitive": False},
        },
    )
    print(f"created evaluator quality ({ev['id']})")
    return ev["id"]


def create_and_evaluate(
    base: str,
    project_id: str,
    *,
    name: str,
    dataset_id: str,
    evaluator_id: str,
    baseline_experiment_id: str | None = None,
    model_config: dict[str, Any] | None = None,
) -> str:
    body: dict[str, Any] = {
        "name": name,
        "dataset_id": dataset_id,
        "model_config": model_config or {},
        "version": name,
    }
    if baseline_experiment_id:
        body["baseline_experiment_id"] = baseline_experiment_id
    experiment = http_json(
        "POST",
        f"{base}/api/v1/projects/{project_id}/experiments",
        body=body,
    )
    experiment_id = experiment["id"]
    evaluated = http_json(
        "POST",
        f"{base}/api/v1/experiments/{experiment_id}/evaluate",
        body={"evaluator_ids": [evaluator_id]},
    )
    run = evaluated["runs"][0]
    print(
        f"experiment {name}: status={evaluated['experiment']['status']} run={run['status']}"
    )
    summary = http_json("GET", f"{base}/api/v1/experiments/{experiment_id}/summary")
    for row in summary.get("evaluators") or []:
        print(
            f"  {row.get('evaluator_name')}: mean={row.get('mean_score')} "
            f"pass_rate={row.get('pass_rate')}"
        )
    return experiment_id


def write_policy(
    *,
    base: str,
    project_id: str,
    experiment_id: str,
    baseline_experiment_id: str,
) -> Path:
    text = f"""# Generated by scripts/portfolio_demo.py — meta fields stripped by CLI.
api_base_url: {base}
project_id: {project_id}
experiment_id: {experiment_id}
baseline_experiment_id: {baseline_experiment_id}

quality:
  min: 0.8
regression:
  max_delta: -0.05
"""
    POLICY_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {POLICY_PATH}")
    return POLICY_PATH


def run_aiobs_check(policy: Path, base: str) -> int:
    cmd = [
        "uv",
        "run",
        "aiobs",
        "check",
        "--policy",
        str(policy),
        "--base-url",
        base,
    ]
    print("running:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(CLI_DIR), check=False)
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", default=os.getenv("AIOBS_BASE_URL", "http://localhost:8000")
    )
    parser.add_argument("--project-slug", default="hr-it-assistant")
    parser.add_argument(
        "--skip-check", action="store_true", help="Skip aiobs check subprocess"
    )
    args = parser.parse_args(argv)

    base = args.base_url.rstrip("/")
    health = http_json("GET", f"{base}/health")
    if not health or health.get("status") != "ok":
        raise SystemExit(f"API unhealthy at {base}/health: {health}")

    warn_content_capture(base)
    project = ensure_project(base, args.project_slug, "Acme People Ops")
    project_id = project["id"]

    stamp = time.strftime("%Y%m%d-%H%M%S")
    model1 = os.getenv("OLLAMA_MODEL1", os.getenv("OLLAMA_MODEL", "gemma4:e2b"))
    model2 = os.getenv("OLLAMA_MODEL2", "tinyllama")
    print(f"MODEL1 (baseline)={model1}")
    print(f"MODEL2 (candidate)={model2}")

    env_extra = {
        "AIOBS_OTLP_ENDPOINT": f"{base}/v1/traces",
        "OLLAMA_HOST": os.getenv("OLLAMA_HOST", "http://localhost:11434"),
    }

    runs1 = run_assistant(model1, project_slug=args.project_slug, env_extra=env_extra)
    runs2 = run_assistant(model2, project_slug=args.project_slug, env_extra=env_extra)

    baseline_ds = create_dataset_from_runs(
        base, project_id, name=f"people-ops-m1-{stamp}", runs=runs1
    )
    candidate_ds = create_dataset_from_runs(
        base, project_id, name=f"people-ops-m2-{stamp}", runs=runs2
    )

    evaluator_id = ensure_quality_evaluator(base, project_id)
    baseline_id = create_and_evaluate(
        base,
        project_id,
        name=f"baseline-{stamp}",
        dataset_id=baseline_ds,
        evaluator_id=evaluator_id,
        model_config={"model": model1},
    )
    candidate_id = create_and_evaluate(
        base,
        project_id,
        name=f"candidate-{stamp}",
        dataset_id=candidate_ds,
        evaluator_id=evaluator_id,
        baseline_experiment_id=baseline_id,
        model_config={"model": model2},
    )

    compare = http_json(
        "GET",
        f"{base}/api/v1/experiments/{candidate_id}/compare/{baseline_id}",
    )
    print("compare:")
    print(json.dumps(compare, indent=2))

    policy = write_policy(
        base=base,
        project_id=project_id,
        experiment_id=candidate_id,
        baseline_experiment_id=baseline_id,
    )

    print(f"\nOpen UI: http://localhost:3000  (project slug={args.project_slug})")
    print(f"API project id: {project_id}")

    if args.skip_check:
        print("skipping aiobs check")
        return 0

    code = run_aiobs_check(policy, base)
    if code == 0:
        print("gate passed")
        return 0
    if code == 1:
        print("gate failed (regression or quality threshold)")
        return 0
    print(f"aiobs check failed with unexpected exit {code}", file=sys.stderr)
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or exc, file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
