# Acme People Ops Assistant — Portfolio Demo Design

**Date:** 2026-10-02  
**Status:** Approved  
**Replaces:** `examples/rag_faq` (removed)

## Goal

Replace the toy meta FAQ demo with a **credible mini-product** so a developer can:

1. run a full quality loop (traces → dataset → experiments → compare → `aiobs check`);
2. compare **two Ollama models** (`MODEL1` vs `MODEL2`) on the same retrieval/prompt pipeline;
3. see real score deltas without config cheats or hardcoded bad answers.

This demo is the primary narrative for the platform’s stated fit: RAG / FAQ with checkable ground truth.

## Product

| Field | Value |
|---|---|
| Product name | Acme People Ops Assistant |
| Path | `examples/hr_it_assistant/` |
| Project slug | `hr-it-assistant` |
| Service name | `hr-it-assistant` |
| Language | English only |
| UI | None (CLI + Ollama + SDK) |

Internal chatbot that answers **only** from a fictional Acme HR/IT policy knowledge base.

### Non-goals

- Embeddings / vector DB
- Chat UI, auth, persistence beyond files
- Flaky Ollama-backed tests in CI (demo remains local/manual, same as today)
- LLM-judge as the primary release gate for the portfolio script
- Fake “degraded retrieval” modes (no `good`/`broken`/`degraded` config knobs)

## Knowledge base

File: `examples/hr_it_assistant/knowledge.json`

~8–12 policy documents covering:

- PTO / vacation
- Remote / hybrid work
- VPN / remote access
- Expense reports
- Laptop / device requests
- Password reset / MFA
- Badge / building access (onboarding)
- Benefits / health insurance (1–2 entries)

Each document:

```json
{
  "id": "pto",
  "title": "Paid Time Off",
  "body": "…policy text with concrete facts…",
  "keywords": ["pto", "vacation", "leave", "days"],
  "gold": [
    {
      "question": "How many PTO days do full-time employees get per year?",
      "must_contain": "20 days"
    }
  ]
}
```

Rules for gold:

- `must_contain` is a short verbatim (or near-verbatim) phrase present in `body`.
- Questions are the evaluation set used by `--all` / portfolio demo.
- No meta content about aiobs itself.

## Runtime pipeline

1. Load `knowledge.json`.
2. Retrieve top-k docs with **keyword/token scoring** (no embeddings). Same retrieval for every run.
3. Build a grounded prompt: answer only from context; if insufficient, say you don’t know. Same prompt for every run.
4. Call Ollama via OpenAI-compatible API; **only the model id changes** between compared runs.
5. Emit OpenInference spans through the aiobs SDK:
   - parent `CHAIN` (`people-ops-rag`)
   - child `RETRIEVER` (`people-ops-retrieve`)
   - LLM span from OpenAI instrumentation

CLI:

```bash
# single question with an explicit model
uv run --extra openai --with openai python ../examples/hr_it_assistant/main.py \
  --model gemma4:e2b "How many PTO days do full-time employees get per year?"

# all gold questions (portfolio)
… main.py --model "$OLLAMA_MODEL1" --all --json
```

Env:

- `AIOBS_PROJECT_SLUG` (default `hr-it-assistant`)
- `AIOBS_OTLP_ENDPOINT`
- `OLLAMA_HOST` (default `http://localhost:11434`)
- `OLLAMA_MODEL` — default model for single runs if `--model` omitted
- `OLLAMA_MODEL1` / `OLLAMA_MODEL2` — used by `portfolio_demo.py` (baseline vs candidate)

There is **no** `--mode good|degraded`. The only intentional difference between the two portfolio legs is the chat model.

**Honesty rules (must not ship):**

- No hardcoded answer strings forced after the model call.
- No appending `must_contain` to the model output to force `contains` to pass.
- If a model omits the gold phrase, the sample fails — that is the signal.

## Evaluation & portfolio loop

`scripts/portfolio_demo.py` updates:

1. Create/reuse project `hr-it-assistant`.
2. Resolve models from env (with documented defaults the user can override):
   - `OLLAMA_MODEL1` → baseline (intended stronger model)
   - `OLLAMA_MODEL2` → candidate (intended weaker / alternate model)
3. Run all gold questions with `MODEL1`, then again with `MODEL2` (identical retrieval + prompt).
4. Build datasets via `from-trace` (same CONTENT_CAPTURE requirement).
5. Evaluator `quality`: deterministic `contains`, case-insensitive, expected = `must_contain`.
6. Baseline experiment = `MODEL1`; candidate = `MODEL2` (`model_config` records the model id).
7. Write `examples/hr_it_assistant/aiobs.yaml`.
8. Run `aiobs check` and print the exit code + compare summary.

### Gate expectation (important)

Unlike the old `broken` demo, **exit code 1 is not guaranteed**. Outcome depends on the two models the operator pulls:

- If `MODEL2` is meaningfully weaker on the gold phrases → gate often fails (good portfolio story).
- If both models nail `must_contain` → gate may pass; the compare UI still shows the experiment pair.

README must say: pick a stronger `OLLAMA_MODEL1` and a weaker `OLLAMA_MODEL2` (examples listed; user-owned). `portfolio_demo.py` should treat exit `0` and `1` as successful script completion when the loop finished cleanly, and only fail the script on infra/config errors (`2`/`3` or subprocess crashes). Print a clear line: `gate passed` vs `gate failed (regression or quality threshold)`.

Policy shape (unchanged semantics):

```yaml
quality:
  min: 0.8
regression:
  max_delta: -0.05
```

## File layout

```
examples/hr_it_assistant/
  README.md
  main.py
  knowledge.json
  aiobs.yaml          # generated by portfolio_demo (same practice as today)
```

## Migration

**Remove**

- `examples/rag_faq/` entirely

**Update references**

- `scripts/portfolio_demo.py` (paths, slug, `MODEL1`/`MODEL2`, naming)
- Root `README.md` portfolio section
- Any docs that cite RAG FAQ portfolio / `examples/rag_faq`
- `docs/02-domain-model.md` example wording if it cites “RAG FAQ”
- `sdk/README.md` only if it documents the portfolio example path (fixture names in unit tests may keep the string `rag-faq` — unrelated app-config fixture)

**Do not require** renaming unrelated test fixtures that happen to use `"rag-faq"`.

## Success criteria

- [ ] Clone → compose → pull two Ollama models → set `OLLAMA_MODEL1`/`OLLAMA_MODEL2` → `portfolio_demo.py` completes the loop and prints compare + gate result.
- [ ] Single-question CLI works with `--model` / `OLLAMA_MODEL`.
- [ ] Retrieval and prompt are identical across the two legs; only the model changes.
- [ ] No answer cheating (`must_contain` append / forced stub answers).
- [ ] `examples/rag_faq` gone; docs/README point at `hr_it_assistant`.
- [ ] English-only corpus; product reads as Acme People Ops, not “docs about this repo”.

## Out of scope (follow-ups)

- Embedding retrieval mode
- Optional LLM-judge secondary metric in the portfolio script
- Promoting this demo into automated CI (Ollama dependency)
- Intentional retrieval-degradation modes
