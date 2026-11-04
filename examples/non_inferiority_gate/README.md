# Non-inferiority gate: "the PR must be *shown* to be at least as good as main"

The default `regression` check fails a PR only on a **proven** drop: the 95% paired
bootstrap CI of the mean change lies entirely below 0. On a small or noisy test set most
real drops are not proven, so they pass. "Equal or better" ends up meaning "we could not
prove it is worse".

`regression.non_inferiority_margin` reverses the burden of proof. The PR passes only when
the data shows it is at most `margin` worse than the baseline: the **lower bound** of the
same 95% CI must be `>= -margin`.

```yaml
regression:
  non_inferiority_margin: 0.05   # check regression.<metric>.non_inferiority
```

Same toy RAG pipeline and 20-question gold set as
[`ci_regression_gate`](../ci_regression_gate/README.md). No LLM, no server.

## Try it locally (~30 s)

```bash
cd backend && uv sync --all-extras && cd ..
./examples/non_inferiority_gate/run_demo.sh
```

## What `run_demo.sh` does

The script clears a local SQLite store, then runs four `opengrade evaluate` steps. Each step prints the CLI summary and checks the exit code.

| Step | Simulates | Config | Bug | Result |
|------|-----------|--------|-----|--------|
| 1 | push to `main` | [`opengrade.yaml`](opengrade.yaml) | — | PASS + `--promote main` |
| 2 | PR, same answers | non-inferiority | — | PASS: CI `[0, 0]` |
| 3 | PR loses a document | [`opengrade.classic.yaml`](opengrade.classic.yaml) | `RAG_DROP_DOC=travel` | **PASS**: Δ −0.10, "not significant" |
| 4 | same PR | non-inferiority | `RAG_DROP_DOC=travel` | **FAIL**: CI lower bound &lt; −margin |

Steps 3 and 4 are the point: **same broken PR, two policies**.

### Step 1 — push to `main` (bootstrap)

```bash
opengrade evaluate --config opengrade.yaml --version main-1 --promote main
```

Runs the 20 questions on the healthy pipeline (scores 1.0). There is no baseline yet, so
only the absolute floors (`hit_at_k.min`, `must_contain.min`) apply. `--promote main`
stores the experiment as alias `main` in `ci.db`. Exit 0.

### Step 2 — PR refactor, unchanged answers

```bash
opengrade evaluate --config opengrade.yaml --version pr-1 --require-baseline
```

Same code, same answers → every paired Δ is 0, CI is `[0, 0]`. Compared against
`alias:main`. Both the classic `regression.*.mean_score` checks and
`regression.*.non_inferiority` pass. Exit 0.

Message: unchanged deterministic code always clears non-inferiority.

### Step 3 — same bug, **classic** policy

```bash
RAG_DROP_DOC=travel opengrade evaluate --config opengrade.classic.yaml \
  --version pr-2 --require-baseline
```

`RAG_DROP_DOC=travel` drops the travel doc from the index; 2 of 20 answers break
(mean 0.90, Δ −0.10). `opengrade.classic.yaml` has `regression: {}` — only the default
check ("fail if the CI lies entirely below 0").

The CI is about `[-0.25, 0.00]`: not entirely below 0, so the drop is "not significant".
Floors at 0.8 still pass. Exit **0** — classic policy ships a real but unproven drop on
n=20.

### Step 4 — same bug, **non-inferiority** policy

```bash
RAG_DROP_DOC=travel opengrade evaluate --config opengrade.yaml \
  --version pr-2 --require-baseline
```

Same pipeline, same Δ −0.10 and CI `[-0.25, 0]`, but `opengrade.yaml` requires the CI
lower bound `>= -0.05`. Lower bound −0.25 fails `regression.*.non_inferiority`; the
classic `mean_score` checks stay green. Exit **1**.

```text
regression.hit_at_k.mean_score         -0.10   n/a     passed   ← classic check
regression.hit_at_k.non_inferiority    -0.25   -0.05   failed   ← CI lower bound
Result: FAILED
```

Broken answers show up in the CLI under "Test cases worse than baseline".

## How to use this

In CI, wire it up exactly like [`ci_regression_gate`](../ci_regression_gate/README.md):
`--require-baseline` on pull requests, `--promote main` on push to `main`.

More: [`docs/08-cli-ci.md`](../../docs/08-cli-ci.md#non-inferiority-regressionnon_inferiority_margin).
