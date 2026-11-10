"""05 - Prompt A/B through versioned App Configs.

Use case: "Same model and retriever — which system prompt is better?"

The variable under test is the generation prompt, not the model. OpenGrade stores each
prompt as an App Config version; the experiment snapshots that version, so a compare in
the UI always shows *which* prompt produced the scores (Experiments -> App config
snapshot).

What this script shows, step by step:

  1. Create two App Config versions of the same family (identical model / retrieval,
     different ``prompt.system``).
  2. Run ``evaluate`` once per version, bound with ``app_config_id``; the task reads
     ``prompt.system`` from the experiment's snapshot (``exp.params``).
  3. Compare candidate vs baseline and print the App Config ids to open in the UI.

Offline (default ``fake-*`` models) the fake LLM barely uses the system text, so scores
may look similar — the point is the App Config / snapshot workflow. With a real model
(``TOUR_MODEL=gemma4:e2b``) the stricter candidate prompt usually changes refusals and
length.

Run:  uv run python 05_prompt_ab.py
      TOUR_MODEL=gemma4:e2b uv run python 05_prompt_ab.py
Then: UI -> Experiments (open each run's App config snapshot).
"""

from __future__ import annotations

import sys
import time
from typing import Any

import opengrade
from opengrade import Opengrade, Settings

from nimbus_apps import settings
from nimbus_apps.console import note, step, title
from nimbus_apps.datasets import RAG_GOLD, ensure_dataset
from nimbus_apps.quality import cites_retrieved_source, refusal_is_correct
from nimbus_apps.rag import DEFAULT_CONFIG, PROMPTS, answer_question

CONFIG_FAMILY = "nimbus-support-rag"

# Baseline = the tour's usual v2 prompt. Candidate = stricter (one sentence, fixed refusal).
BASELINE_SYSTEM = PROMPTS["v2"]
CANDIDATE_SYSTEM = (
    "You are the Nimbus support assistant. Reply in exactly one short sentence using "
    "ONLY the context. Cite the source id in square brackets, e.g. [plans]. If the "
    "context does not contain the answer, reply exactly: "
    '"I don\'t know: the Nimbus documentation does not cover this."'
)

METRICS: list[Any] = [
    "hit_at_k",
    "must_contain",
    "latency",
    cites_retrieved_source,
    refusal_is_correct,
]


def system_prompt_from_params(params: dict[str, Any]) -> str:
    """``prompt.system`` from the App Config snapshot stored on the experiment."""
    prompt = params.get("prompt")
    if isinstance(prompt, dict):
        system = prompt.get("system")
        if isinstance(system, str) and system.strip():
            return system.strip()
    raise RuntimeError(
        "experiment params missing prompt.system — was the run bound to an App Config?"
    )


def run_with_app_config(
    og: Opengrade,
    *,
    name: str,
    app_config_id: str,
    baseline: str | None,
    metrics: list[Any],
) -> opengrade.ExperimentResult:
    """One evaluated run whose params are the App Config snapshot."""
    exp = og.start_experiment(
        name,
        dataset=RAG_GOLD,
        metrics=metrics,
        app_config_id=app_config_id,
        baseline=baseline,
    )
    system = system_prompt_from_params(exp.params)
    print(f"  system prompt ({len(system)} chars): {system[:72]}…")

    def task(item: Any) -> str:
        return answer_question(item.input, DEFAULT_CONFIG, system=system)

    exp.run_task(task, max_concurrency=4)
    return exp.finish()


def main() -> None:
    title("OpenGrade SDK tour - 05 Prompt A/B via App Config")

    step(0, "Connect")
    og = Opengrade(Settings(tracking_uri=settings.TRACKING_URI, project_slug=settings.PROJECT))
    with og.activate():
        project = og.set_project(settings.PROJECT)
        if project is None:
            sys.exit(f"OpenGrade is not reachable at {settings.TRACKING_URI}: start it first.")
        og.init_tracing(service_name="nimbus-support-eval", instrument="auto")
        client = og.client
        ensure_dataset(RAG_GOLD)
        metrics = list(METRICS)
        if settings.USE_LLM_JUDGES:
            metrics += ["groundedness", "correctness"]

        stamp = time.strftime("%Y%m%d-%H%M%S")
        model = settings.DEFAULT_MODEL
        print(f"  model (fixed)={model}")
        print("  varying: system prompt via App Config (baseline vs candidate)")

        step(1, "Create two App Config versions (same model/retrieval, different prompt)")
        baseline_cfg = client.app_configs.create_app_config(
            project.id,
            CONFIG_FAMILY,
            description=f"baseline prompt {stamp}",
            prompt={"system": BASELINE_SYSTEM},
            model={"model_id": model},
            retrieval={"top_k": DEFAULT_CONFIG.top_k, "strategy": DEFAULT_CONFIG.retriever},
        )
        candidate_cfg = client.app_configs.create_app_config(
            project.id,
            CONFIG_FAMILY,
            description=f"candidate prompt {stamp}",
            prompt={"system": CANDIDATE_SYSTEM},
            model={"model_id": model},
            retrieval={"top_k": DEFAULT_CONFIG.top_k, "strategy": DEFAULT_CONFIG.retriever},
        )
        print(
            f"  baseline  {baseline_cfg.name}@v{baseline_cfg.version}  id={baseline_cfg.id}"
        )
        print(
            f"  candidate {candidate_cfg.name}@v{candidate_cfg.version}  id={candidate_cfg.id}"
        )
        note(
            """Each create bumps the version of the family. The experiment will freeze the
            chosen version as a snapshot, so later edits to the family do not rewrite history."""
        )

        step(2, "Evaluate baseline, then candidate (bound to each App Config)")
        baseline = run_with_app_config(
            og,
            name=f"prompt-baseline-{stamp}",
            app_config_id=baseline_cfg.id,
            baseline=None,
            metrics=metrics,
        )
        print(baseline.summary())
        candidate = run_with_app_config(
            og,
            name=f"prompt-candidate-{stamp}",
            app_config_id=candidate_cfg.id,
            baseline=baseline.id,
            metrics=metrics,
        )
        print(candidate.summary())

        step(3, "Compare candidate vs baseline")
        compare = client.experiments.compare(candidate.id, baseline.id)
        print(compare.model_dump_json(indent=2))
        note(
            """In the UI, open each run and check App config snapshot: you should see the two
            different system prompts. With fake models the quality delta may be tiny; with a
            real model the stricter candidate often changes must_contain / refusal scores."""
        )

        print(f"\nBaseline:  {baseline.url}")
        print(f"Candidate: {candidate.url}")
        print(f"App config family: {CONFIG_FAMILY}")
    og.flush()


if __name__ == "__main__":
    main()
