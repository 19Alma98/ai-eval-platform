# LLM regression gate

"The PR must not be worse than `main`" for a RAG pipeline with a **real LLM** and an
**LLM judge**. Deterministic version without an LLM:
[`ci_regression_gate`](../ci_regression_gate/README.md).

```bash
ollama pull gemma4:e2b
./examples/llm_regression_gate/run_demo.sh
```

| Step | Simulates | Expected |
|------|-----------|----------|
| 1 | push to `main` | PASS, baseline created |
| 2 | PR, no code change (new LLM samples) | PASS: noise is not a regression |
| 3 | PR that drops the retrieved context from the prompt | **FAIL** |

What [`opengrade.yaml`](opengrade.yaml) adds for an LLM (details in its comments):

| Problem | Setting |
|---------|---------|
| LLM noise looks like a regression | `repeats: 3` |
| Judge changes shift every score | judge pinned, `temperature: 0` |
| A security answer breaks while averages hold | `critical` (`"critical": true` in the gold set) |
| One question breaks, another improves | `regression.max_new_failures` |
| Gold set too small to see a drop | power warning, `max_detectable_delta` |
| "Not proven worse" is not "as good" | `non_inferiority_margin` ([example](../non_inferiority_gate/README.md)) |

CI: [`github-workflow.yml.example`](github-workflow.yml.example). Switch
`evaluate.judge` to a cloud model first. More: [`docs/08-cli-ci.md`](../../docs/08-cli-ci.md).
