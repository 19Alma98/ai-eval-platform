#!/usr/bin/env python3
"""Prompt A/B demo: same KB + model, two App Config prompts → evaluate-pack → compare."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SDK_DIR = ROOT / "sdk"
APP_DIR = ROOT / "examples" / "hr_it_assistant"
KNOWLEDGE_PATH = APP_DIR / "knowledge.json"
POLICY_PATH = APP_DIR / "aiobs.prompt-ab.yaml"
BACKEND_DIR = ROOT / "backend"

sys.path.insert(0, str(SDK_DIR / "src"))

from aiobs import Client  # noqa: E402

CONFIG_FAMILY = "people-ops-rag"

BASELINE_SYSTEM_PROMPT = (
    "You are Acme's People Ops assistant. Answer using only the provided "
    "policy context. Be concise (1-2 sentences). If the context is insufficient, "
    "say you do not know."
)

CANDIDATE_SYSTEM_PROMPT = (
    "You are Acme's People Ops assistant. Answer using ONLY the provided policy "
    "context — never invent policy details. Reply in exactly one short sentence. "
    "If the context does not contain the answer, reply exactly: I do not know."
)


def ensure_project(client: Client, slug: str, name: str) -> dict[str, Any]:
    for project in client.projects.list():
        if project.get("slug") == slug:
            print(f"reusing project {slug} ({project['id']})")
            return project
    project = client.projects.create(name=name, slug=slug)
    print(f"created project {slug} ({project['id']})")
    return project


def load_gold_rows() -> list[dict[str, Any]]:
    data = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for doc in data:
        doc_id = str(doc["id"])
        for g in doc.get("gold") or []:
            phrase = str(g["must_contain"])
            rows.append(
                {
                    "question": str(g["question"]),
                    "expected_output": phrase,
                    "expected_doc_ids": [doc_id],
                    "must_contain": [phrase],
                }
            )
    if not rows:
        raise RuntimeError(f"no gold rows in {KNOWLEDGE_PATH}")
    return rows


def create_rag_dataset(
    client: Client, project_id: str, *, name: str
) -> tuple[str, dict[str, str]]:
    dataset = client.datasets.create(
        project_id,
        name=name,
        description="People Ops RAG gold (prompt A/B demo)",
        task_type="rag_qa",
    )
    dataset_id = dataset["id"]
    item_map: dict[str, str] = {}
    for row in load_gold_rows():
        item = client.datasets.add_item(
            dataset_id,
            input=row["question"],
            expected_output=row["expected_output"],
            metadata={
                "expected_doc_ids": row["expected_doc_ids"],
                "must_contain": row["must_contain"],
            },
        )
        item_map[row["question"]] = item["id"]
        print(f"  item {item['id'][:8]}… {row['question'][:48]}…")
    return dataset_id, item_map


def ensure_metrics_pack(client: Client, project_id: str) -> None:
    pack = client.metrics_packs.ensure(project_id)
    kinds = [e["kind"] for e in pack.get("entries") or []]
    print(f"metrics pack ready: {', '.join(kinds)}")


def create_app_config(
    client: Client,
    project_id: str,
    *,
    system_prompt: str,
    model: str,
    description: str,
) -> dict[str, Any]:
    created = client.app_configs.create_app_config(
        project_id,
        CONFIG_FAMILY,
        description=description,
        prompt={"system": system_prompt},
        model={"model_id": model},
        retrieval={"top_k": 2},
    )
    print(
        f"app config {created.get('name')}@v{created.get('version')} "
        f"id={created['id'][:8]}… hash={str(created.get('content_hash', ''))[:12]}…"
    )
    return created


def create_experiment(
    client: Client,
    project_id: str,
    *,
    name: str,
    dataset_id: str,
    app_config_id: str,
    baseline_experiment_id: str | None = None,
) -> str:
    experiment = client.experiments.create(
        project_id,
        name=name,
        dataset_id=dataset_id,
        app_config_id=app_config_id,
        version=name,
        baseline_experiment_id=baseline_experiment_id,
    )
    return experiment["id"]


def run_assistant(
    model: str,
    *,
    project_slug: str,
    experiment_id: str,
    system_prompt: str,
    item_map: dict[str, str],
    env_extra: dict[str, str],
) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(item_map, handle, ensure_ascii=True)
        map_path = handle.name
    try:
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
            "--experiment-id",
            experiment_id,
            "--item-map",
            map_path,
        ]
        env = os.environ.copy()
        env.update(env_extra)
        env["AIOBS_PROJECT_SLUG"] = project_slug
        env["AIOBS_EXPERIMENT_ID"] = experiment_id
        env["AIOBS_SYSTEM_PROMPT"] = system_prompt
        env["OLLAMA_MODEL"] = model
        print(
            f"running hr_it_assistant model={model} experiment={experiment_id[:8]}… "
            f"(system_prompt={len(system_prompt)} chars)"
        )
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
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        if len(lines) < len(item_map):
            raise RuntimeError(
                f"expected {len(item_map)} results, got {len(lines)} (model={model})"
            )
    finally:
        Path(map_path).unlink(missing_ok=True)
    time.sleep(1.0)


def wait_for_outputs(
    client: Client, experiment_id: str, expected: int, *, attempts: int = 30
) -> list[dict[str, Any]]:
    last: list[dict[str, Any]] = []
    for _ in range(attempts):
        last = client.experiments.list_outputs(experiment_id)
        if len(last) >= expected:
            return last
        time.sleep(0.5)
    raise RuntimeError(
        f"experiment {experiment_id} has {len(last)}/{expected} bound outputs after ingest"
    )


def evaluate_pack(client: Client, experiment_id: str) -> None:
    evaluated = client.experiments.evaluate_pack(experiment_id)
    run = evaluated["runs"][0] if evaluated.get("runs") else None
    print(
        f"evaluate-pack: status={evaluated['experiment']['status']} "
        f"runs={len(evaluated.get('runs') or [])}"
    )
    if run:
        print(f"  first run status={run.get('status')} results={len(run.get('results') or [])}")
    summary = client.experiments.summary(experiment_id)
    for row in summary.get("evaluators") or []:
        print(
            f"  {row.get('evaluator_name')}: mean={row.get('mean_score')} "
            f"pass_rate={row.get('pass_rate')}"
        )


def write_policy(
    *,
    base: str,
    project_id: str,
    experiment_id: str,
    baseline_experiment_id: str,
) -> Path:
    text = f"""# Generated by scripts/prompt_ab_demo.py — meta fields stripped by CLI.
api_base_url: {base}
project_id: {project_id}
experiment_id: {experiment_id}
baseline_experiment_id: {baseline_experiment_id}

hit_at_k:
  min: 0.8
groundedness:
  min: 0.7
correctness:
  min: 0.7
latency:
  p95_max_ms: 30000
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
    proc = subprocess.run(cmd, cwd=str(BACKEND_DIR), check=False)
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
    client = Client(base, timeout=120.0)
    health = client.health()
    if not health or health.get("status") != "ok":
        raise SystemExit(f"API unhealthy at {base}/health: {health}")

    project = ensure_project(client, args.project_slug, "Acme People Ops")
    project_id = project["id"]
    ensure_metrics_pack(client, project_id)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    model = os.getenv("OLLAMA_MODEL", "gemma4:e2b")
    print(f"MODEL (fixed)={model}")
    print("varying: system prompt via App Config (baseline vs candidate)")

    env_extra = {
        "AIOBS_OTLP_ENDPOINT": f"{base}/v1/traces",
        "OLLAMA_HOST": os.getenv("OLLAMA_HOST", "http://localhost:11434"),
    }

    print(f"creating rag_qa test set people-ops-prompt-ab-{stamp} …")
    dataset_id, item_map = create_rag_dataset(
        client, project_id, name=f"people-ops-prompt-ab-{stamp}"
    )
    expected_items = len(item_map)

    baseline_cfg = create_app_config(
        client,
        project_id,
        system_prompt=BASELINE_SYSTEM_PROMPT,
        model=model,
        description=f"baseline prompt {stamp}",
    )
    candidate_cfg = create_app_config(
        client,
        project_id,
        system_prompt=CANDIDATE_SYSTEM_PROMPT,
        model=model,
        description=f"candidate prompt {stamp}",
    )

    baseline_id = create_experiment(
        client,
        project_id,
        name=f"prompt-baseline-{stamp}",
        dataset_id=dataset_id,
        app_config_id=baseline_cfg["id"],
    )
    run_assistant(
        model,
        project_slug=args.project_slug,
        experiment_id=baseline_id,
        system_prompt=BASELINE_SYSTEM_PROMPT,
        item_map=item_map,
        env_extra=env_extra,
    )
    wait_for_outputs(client, baseline_id, expected_items)
    evaluate_pack(client, baseline_id)

    candidate_id = create_experiment(
        client,
        project_id,
        name=f"prompt-candidate-{stamp}",
        dataset_id=dataset_id,
        app_config_id=candidate_cfg["id"],
        baseline_experiment_id=baseline_id,
    )
    run_assistant(
        model,
        project_slug=args.project_slug,
        experiment_id=candidate_id,
        system_prompt=CANDIDATE_SYSTEM_PROMPT,
        item_map=item_map,
        env_extra=env_extra,
    )
    wait_for_outputs(client, candidate_id, expected_items)
    evaluate_pack(client, candidate_id)

    compare = client.experiments.compare(candidate_id, baseline_id)
    print("compare:")
    print(json.dumps(compare, indent=2))

    policy = write_policy(
        base=base,
        project_id=project_id,
        experiment_id=candidate_id,
        baseline_experiment_id=baseline_id,
    )

    print(f"\nOpen UI: http://localhost:3000  (project slug={args.project_slug})")
    print("Flow: Test set → Runs (App config snapshot shows each prompt)")
    print(f"API project id: {project_id}")
    print(f"App config family: {CONFIG_FAMILY}")

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
