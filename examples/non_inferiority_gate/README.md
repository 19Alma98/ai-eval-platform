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

Same toy pipeline and 20-question gold set as
[`ci_regression_gate`](../ci_regression_gate/README.md). No LLM, no server.

## Try it locally (~30 s)

```bash
cd backend && uv sync --all-extras && cd ..
./examples/non_inferiority_gate/run_demo.sh
```

| Step | Simulates | Policy | Result |
|------|-----------|--------|--------|
| 1 | push to `main` | non-inferiority | PASS, alias `main` created |
| 2 | PR, refactor with the same answers | non-inferiority | PASS: CI `[0, 0]` |
| 3 | PR whose ingestion loses one document (`RAG_DROP_DOC=travel`) | classic ([`opengrade.classic.yaml`](opengrade.classic.yaml)) | **PASS**: 2 of 20 answers break, Δ −0.10, "not significant" |
| 4 | the same PR | non-inferiority ([`opengrade.yaml`](opengrade.yaml)) | **FAIL** |

Steps 3 and 4 are the point: the same PR, two policies.

```text
metric        mean   pass_rate  vs baseline
must_contain  0.900  0.900      -0.100 not significant
hit_at_k      0.900  0.900      -0.100 not significant
…
regression.hit_at_k.mean_score         -0.10   n/a     passed   ← classic check
regression.hit_at_k.non_inferiority    -0.25   -0.05   failed   ← CI lower bound
Result: FAILED
```

The two answers that broke are listed under "Test cases worse than baseline" (CLI and
Markdown report) and in the JUnit failure of each `non_inferiority` check. The report's
"Metrics vs baseline" table shows the 95% CI next to each Δ.

## Choosing the margin

- **The margin is a product decision:** the largest drop you would ship without
  discussion (e.g. 0.02–0.05 on a 0–1 score).
- **The test set must be large enough to show it.** The CI width shrinks roughly with
  `1/sqrt(n)`. With 20 questions a single broken answer already gives a lower bound of
  about −0.15, so a 0.05 margin acts like "no answer may break". The power warning
  ("the comparison resolves only mean changes of about …; about N test cases would be
  needed") tells you how far you are.
- **Deterministic pipeline, unchanged code:** every paired difference is 0 and the CI is
  `[0, 0]`, so it always passes.
- **Sampling LLM / LLM judge:** run-to-run noise widens the CI even when nothing changed.
  Use `evaluate.repeats` (each item's score is the mean of its repeats), a pinned judge
  at temperature 0 (see [`llm_regression_gate`](../llm_regression_gate/README.md)), and
  a margin the noise does not reach. Otherwise unchanged PRs fail.
- **It is added on top of the other checks**, not instead of them. A proven drop still
  fails `regression.<metric>.mean_score`, and `min` floors, `max_delta`, `critical` and
  `max_new_failures` work as before. Latency / cost / token-usage evaluators are not
  checked. Per-group checks (`groups`) keep the default bootstrap check: groups are small
  and their CIs wide.

In CI, wire it up exactly like [`ci_regression_gate`](../ci_regression_gate/README.md):
`--require-baseline` on pull requests, `--promote main` on push to `main`.

More: [`docs/08-cli-ci.md`](../../docs/08-cli-ci.md#non-inferiority-regressionnon_inferiority_margin).
