# CI regression gate: "the PR must not be worse than main"

Runnable example of the most common CI check for a RAG pipeline / LLM app:

- **PR**: run the gold test set, compare against the **last accepted run on `main`**.
  Equal or better → exit `0`. Worse → exit `1`, the PR check goes red. No baseline to
  compare with → also exit `1` (`--require-baseline`), never a silent pass.
- **Push to `main`**: same run; when the gate passes, that run becomes the new baseline
  (`--promote main`). A failed run never becomes the baseline.

The pipeline in [`rag_app.py`](rag_app.py) is deterministic (keyword retriever + extractive
answer), so the demo needs no LLM and no API key. Replace `task()` with your own pipeline.

## Try it locally (~30 s)

```bash
cd backend && uv sync --all-extras && cd ..
./examples/ci_regression_gate/run_demo.sh
```

| Step | Simulates | Result |
|------|-----------|--------|
| 0 | PR before `main` ever ran (`--require-baseline`) | **FAIL** on `baseline.required` |
| 1 | first push to `main` (no baseline yet) | PASS, alias `main` created |
| 2 | PR with a refactor that keeps quality | PASS (deltas `0.0`) |
| 3 | PR with a buggy tokenizer (`RAG_TOKENIZER=raw`) | **FAIL**, alias not moved |

Step 3 is the interesting one. The regressed PR still scores `hit_at_k = 0.80`, which is
exactly the absolute floor (`min: 0.8`): **an absolute threshold alone would let it ship**.
What blocks it is the comparison with the baseline:

```text
regression.hit_at_k.mean_score       -0.20   -0.05   failed
regression.must_contain.mean_score   -0.20   -0.05   failed
groups.category=it.hit_at_k.min       0.67    0.8    failed
groups.category=finance.hit_at_k.min  0.67    0.8    failed
Alias 'main' not moved: the gate failed
Result: FAILED
```

Each step also writes `reports/stepN.md` (what the job summary / PR comment shows)
and `reports/stepN.xml` (JUnit, one test case per check).

## How the policy works ([`opengrade.yaml`](opengrade.yaml))

| Block | Question it answers |
|-------|---------------------|
| `hit_at_k.min`, `must_contain.min` | Is the run good enough in absolute terms? |
| `latency.p95_max_ms` | Is it fast enough? (`max_increase_pct` adds "not slower than main by more than N%") |
| `experiment_metrics` | Run-level numbers: `opengrade.error_rate` must stay under 5% **and** not grow vs main (`max_increase: 0.0`). |
| `regression` | Is any metric **worse than the baseline**? Fails on a statistically significant drop (paired bootstrap, CI entirely below 0) **or** a mean drop larger than `max_delta`. |
| `groups.by: category` | Same checks per question category, so one category collapsing is not hidden by the global mean. |

Keep both kinds of rules: `regression` alone can drift down over many small
"not significant" drops; `min` alone misses drops that stay above the floor.

Rules of thumb:

- At least **5 paired items per metric** (and per group, `min_items`) are needed for the
  regression check; below that it is reported as `unavailable`, which fails the gate.
  Aim for 30+ gold items for meaningful statistics.
- If the pipeline is non-deterministic (real LLM), set `evaluate.repeats: 3` so noise does
  not look like a regression.
- Changing the dataset or the metrics set makes the comparison meaningless: that run skips
  `regression` (`Exam changed`) and re-bases when it passes.

## In GitHub Actions

[`github-workflow.yml.example`](github-workflow.yml.example) wires it up:

```bash
# pull_request: must be compared with main
opengrade evaluate --config opengrade.yaml --version "$GITHUB_SHA" --require-baseline \
  --report-md .opengrade/report.md --junit .opengrade/junit.xml
# push to main: may bootstrap / re-base the alias
opengrade evaluate --config opengrade.yaml --version "$GITHUB_SHA" --promote main
```

The baseline must outlive a single CI job. Either point `api_base_url` / `--base-url` at a
shared OpenGrade server (recommended: you also get the compare UI and history), or keep a
SQLite store in the Actions cache, as the workflow does when `OPENGRADE_BASE_URL` is empty.
The workflow puts the Markdown report in the job summary and in a sticky PR comment, and
publishes the JUnit file as a check. A PR that intentionally changes the gold set gets
the `opengrade:exam-change` label to run without `--require-baseline`.

Promote only from `main`, never from pull requests: a PR that passes is not merged code.

More: [`docs/08-cli-ci.md`](../../docs/08-cli-ci.md).
