# HR/IT Assistant Portfolio Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `examples/rag_faq` with a credible Acme People Ops RAG assistant and a portfolio loop that compares `OLLAMA_MODEL1` vs `OLLAMA_MODEL2` (same retrieval/prompt; no answer cheating).

**Architecture:** Self-contained CLI app under `examples/hr_it_assistant/` loads a JSON knowledge base, keyword-retrieves docs, calls Ollama via OpenAI-compatible API, and exports OpenInference traces through the aiobs SDK. `scripts/portfolio_demo.py` runs all gold questions twice (model1 baseline, model2 candidate), builds datasets, evaluates with `contains`, compares, and runs `aiobs check` without requiring gate failure.

**Tech Stack:** Python 3.12, aiobs SDK (`@aiobs.trace`, OpenAI instrumentor), OpenAI client → Ollama, stdlib JSON/argparse, existing portfolio HTTP helpers.

**Spec:** `docs/superpowers/specs/2026-10-02-hr-it-assistant-portfolio-design.md`

## Global Constraints

- English-only corpus; product is **Acme People Ops Assistant**, not docs about this repo.
- **No** `--mode good|degraded|broken`; only model id differs between compared runs.
- **No** hardcoded stub answers; **no** appending `must_contain` to force pass.
- Retrieval: keyword/token scoring only (no embeddings).
- Portfolio treats `aiobs check` exit `0` and `1` as successful script completion; fail only on infra/config (`2`/`3`) or crashes.
- Do **not** rename unrelated unit-test fixtures that use the string `"rag-faq"`.
- Prefer TDD for pure retrieval/KB helpers; do not add Ollama-backed CI tests.

## File map

| Path | Responsibility |
|------|----------------|
| `examples/hr_it_assistant/knowledge.json` | Policies + gold Q/`must_contain`/keywords |
| `examples/hr_it_assistant/kb.py` | Load KB, retrieve, list gold questions, resolve expected phrase |
| `examples/hr_it_assistant/test_kb.py` | Unit tests for `kb.py` (no Ollama) |
| `examples/hr_it_assistant/main.py` | CLI: retrieve → prompt → Ollama → SDK traces |
| `examples/hr_it_assistant/README.md` | How to run single Q + portfolio + MODEL1/MODEL2 |
| `examples/hr_it_assistant/aiobs.yaml` | Written by portfolio_demo (generated) |
| `scripts/portfolio_demo.py` | Full loop for hr-it-assistant + two models |
| `README.md`, `docs/02-domain-model.md` | Point at new example; drop rag_faq |
| `examples/rag_faq/**` | Delete entirely |
| Spec status line | Mark approved |

---

### Task 1: Knowledge base + retrieval helpers (TDD)

**Files:**
- Create: `examples/hr_it_assistant/knowledge.json`
- Create: `examples/hr_it_assistant/kb.py`
- Create: `examples/hr_it_assistant/test_kb.py`

**Interfaces:**
- Produces:
  - `load_knowledge(path: Path | None = None) -> list[dict]`
  - `retrieve(docs: list[dict], question: str, *, top_k: int = 2) -> list[dict]`
  - `iter_gold(docs: list[dict]) -> list[tuple[str, str]]`  # (question, must_contain)
  - `expected_for_question(docs: list[dict], question: str) -> str | None`

- [ ] **Step 1: Write failing unit tests**

```python
# examples/hr_it_assistant/test_kb.py
from __future__ import annotations

from pathlib import Path

from kb import expected_for_question, iter_gold, load_knowledge, retrieve

HERE = Path(__file__).resolve().parent


def test_load_knowledge_has_at_least_eight_docs() -> None:
    docs = load_knowledge(HERE / "knowledge.json")
    assert len(docs) >= 8
    assert all("id" in d and "body" in d and "gold" in d for d in docs)


def test_every_must_contain_appears_in_body() -> None:
    docs = load_knowledge(HERE / "knowledge.json")
    for doc in docs:
        body_l = doc["body"].lower()
        for g in doc["gold"]:
            assert g["must_contain"].lower() in body_l, (doc["id"], g)


def test_retrieve_ranks_pto_question() -> None:
    docs = load_knowledge(HERE / "knowledge.json")
    hits = retrieve(docs, "How many PTO days do full-time employees get?", top_k=2)
    assert hits
    assert hits[0]["id"] == "pto"


def test_iter_gold_and_expected() -> None:
    docs = load_knowledge(HERE / "knowledge.json")
    gold = iter_gold(docs)
    assert len(gold) >= 8
    q, must = gold[0]
    assert expected_for_question(docs, q) == must
```

- [ ] **Step 2: Run tests — expect fail (missing module / knowledge)**

Run: `cd examples/hr_it_assistant && python -m pytest test_kb.py -v`  
Expected: import or file-not-found failure

- [ ] **Step 3: Write `knowledge.json` (full content)**

Create `examples/hr_it_assistant/knowledge.json` with **exactly** these eight documents (English):

```json
[
  {
    "id": "pto",
    "title": "Paid Time Off",
    "body": "Full-time Acme employees receive 20 days of paid time off (PTO) per calendar year. PTO accrues monthly. Unused PTO may roll over up to 5 days into the next year. Requests require manager approval in Workday at least 2 weeks in advance for absences longer than 3 days.",
    "keywords": ["pto", "vacation", "leave", "time off", "days", "roll over"],
    "gold": [
      {
        "question": "How many PTO days do full-time employees get per year?",
        "must_contain": "20 days"
      }
    ]
  },
  {
    "id": "remote",
    "title": "Hybrid and Remote Work",
    "body": "Acme default schedule is hybrid: at least 3 office days per week. Fully remote roles must be approved by HRBP and the department VP. Core collaboration hours are 10:00–16:00 in the employee's local timezone.",
    "keywords": ["remote", "hybrid", "office", "wfh", "work from home"],
    "gold": [
      {
        "question": "How many office days per week does the hybrid policy require?",
        "must_contain": "3 office days"
      }
    ]
  },
  {
    "id": "vpn",
    "title": "VPN and Remote Access",
    "body": "Employees must use the Acme GlobalProtect VPN when accessing internal systems from outside the corporate network. MFA is required for every VPN login. Personal devices are not permitted on VPN; use a company-managed laptop only.",
    "keywords": ["vpn", "globalprotect", "remote access", "mfa", "network"],
    "gold": [
      {
        "question": "Which VPN client should I use for remote access?",
        "must_contain": "GlobalProtect"
      }
    ]
  },
  {
    "id": "expenses",
    "title": "Expense Reports",
    "body": "Submit expense reports in Concur within 30 days of the purchase date. Meal limit for individual dinners is $75 USD without VP approval. Alcohol is not reimbursable. Keep itemized receipts for any expense above $25.",
    "keywords": ["expense", "concur", "reimburse", "receipt", "meal"],
    "gold": [
      {
        "question": "Where do I submit expense reports?",
        "must_contain": "Concur"
      }
    ]
  },
  {
    "id": "laptop",
    "title": "Laptop and Device Requests",
    "body": "New hire laptops are ordered automatically by IT. Replacement or upgrade requests go through the ServiceNow catalog item Hardware Request. Standard issue is a 14-inch MacBook Pro unless a Windows machine is required for the role.",
    "keywords": ["laptop", "hardware", "macbook", "servicenow", "device"],
    "gold": [
      {
        "question": "How do I request a laptop replacement?",
        "must_contain": "ServiceNow"
      }
    ]
  },
  {
    "id": "password",
    "title": "Password Reset and MFA",
    "body": "Password resets are self-service at https://aka.ms/sspr. If locked out of MFA, contact the IT Service Desk at it-help@acme.example or extension 4357. Hardware security keys are mandatory for engineering and finance staff.",
    "keywords": ["password", "reset", "mfa", "sspr", "lockout"],
    "gold": [
      {
        "question": "Where can I reset my password?",
        "must_contain": "aka.ms/sspr"
      }
    ]
  },
  {
    "id": "badge",
    "title": "Badge and Building Access",
    "body": "New employees collect their badge from Building Security on day one after completing onboarding in Workday. Lost badges must be reported within 24 hours to security@acme.example. Guest badges are valid for a single business day.",
    "keywords": ["badge", "building", "security", "access", "guest"],
    "gold": [
      {
        "question": "Who do I contact if I lose my badge?",
        "must_contain": "security@acme.example"
      }
    ]
  },
  {
    "id": "benefits",
    "title": "Health Insurance Benefits",
    "body": "Acme offers medical, dental, and vision coverage through Northwind Health. Open enrollment runs each November. New hires must elect benefits within 30 days of their start date or wait until the next open enrollment.",
    "keywords": ["benefits", "health", "insurance", "enrollment", "dental"],
    "gold": [
      {
        "question": "Through which provider is Acme health insurance offered?",
        "must_contain": "Northwind Health"
      }
    ]
  }
]
```

- [ ] **Step 4: Implement `kb.py`**

```python
# examples/hr_it_assistant/kb.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_KB = HERE / "knowledge.json"


def load_knowledge(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or DEFAULT_KB
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("knowledge.json must be a JSON array")
    return data


def retrieve(
    docs: list[dict[str, Any]], question: str, *, top_k: int = 2
) -> list[dict[str, Any]]:
    q = question.lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in docs:
        score = 0
        for kw in item.get("keywords") or []:
            if str(kw).lower() in q:
                score += 2
        for token in (item.get("title") or "").lower().split():
            if len(token) > 3 and token in q:
                score += 1
        for token in (item.get("body") or "").lower().split():
            if len(token) > 5 and token in q:
                score += 1
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:top_k]]


def iter_gold(docs: list[dict[str, Any]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for doc in docs:
        for g in doc.get("gold") or []:
            out.append((str(g["question"]), str(g["must_contain"])))
    return out


def expected_for_question(docs: list[dict[str, Any]], question: str) -> str | None:
    q = question.lower().strip()
    for gq, must in iter_gold(docs):
        if gq.lower().strip() == q:
            return must
    hits = retrieve(docs, question, top_k=1)
    if hits:
        gold = hits[0].get("gold") or []
        if gold:
            return str(gold[0]["must_contain"])
    return None
```

- [ ] **Step 5: Run tests — expect pass**

Run: `cd examples/hr_it_assistant && python -m pytest test_kb.py -v`  
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add examples/hr_it_assistant/knowledge.json examples/hr_it_assistant/kb.py examples/hr_it_assistant/test_kb.py
git commit -m "$(cat <<'EOF'
feat: add Acme People Ops knowledge base and retrieval helpers

EOF
)"
```

---

### Task 2: CLI app (`main.py`) — honest RAG, model flag

**Files:**
- Create: `examples/hr_it_assistant/main.py`
- Modify: none yet
- Test: manual smoke (optional); reuse Task 1 tests for KB

**Interfaces:**
- Consumes: `kb.load_knowledge`, `kb.retrieve`, `kb.iter_gold`, `kb.expected_for_question`
- Produces: CLI exit 0; JSON lines with `question`, `answer`, `model`, `doc_ids`, `trace_id`, `expected_output`

- [ ] **Step 1: Implement `main.py` (no answer cheating)**

Adapt from the old FAQ app structure, but:

- Use `--model` / `OLLAMA_MODEL` (default `gemma4:e2b`)
- Use `--all` (not `--all-faq`) to run every gold question
- Always retrieve with `top_k=2` and the same grounded system prompt
- **Never** overwrite the model answer; **never** append `must_contain`

```python
# examples/hr_it_assistant/main.py
"""Acme People Ops Assistant — FAQ RAG demo via aiobs SDK + Ollama."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import aiobs
from openai import OpenAI

from kb import expected_for_question, iter_gold, load_knowledge, retrieve

SYSTEM_PROMPT = (
    "You are Acme's People Ops assistant. Answer using only the provided "
    "policy context. Be concise (1-2 sentences). If the context is insufficient, "
    "say you do not know."
)


@aiobs.trace(
    name="people-ops-retrieve",
    kind="RETRIEVER",
    capture_input=False,
    capture_output=True,
)
def retrieve_traced(
    question: str, docs: list[dict[str, Any]], *, top_k: int = 2
) -> list[dict[str, Any]]:
    aiobs.set_input(question)
    hits = retrieve(docs, question, top_k=top_k)
    aiobs.set_attributes(
        {
            "retrieval.document_count": len(hits),
            "retrieval.documents": [
                {"id": d["id"], "title": d.get("title")} for d in hits
            ],
        }
    )
    if not hits:
        aiobs.set_error("no documents")
    return hits


def call_ollama(client: OpenAI, *, model: str, user_prompt: str) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    return (response.choices[0].message.content or "").strip()


@aiobs.trace(
    name="people-ops-rag", kind="CHAIN", capture_input=False, capture_output=False
)
def answer_question(
    question: str,
    *,
    docs: list[dict[str, Any]],
    client: OpenAI,
    model: str,
) -> dict[str, Any]:
    aiobs.set_input(question)
    aiobs.set_attribute("llm.model", model)

    hits = retrieve_traced(question, docs, top_k=2)
    if hits:
        context = "\n\n".join(
            f"Title: {d['title']}\n{d['body']}" for d in hits
        )
        user_prompt = f"Context:\n{context}\n\nQuestion: {question}\nAnswer:"
    else:
        user_prompt = (
            f"No policy context was retrieved.\n\nQuestion: {question}\nAnswer:"
        )

    answer = call_ollama(client, model=model, user_prompt=user_prompt)
    aiobs.set_output(answer)
    return {
        "question": question,
        "answer": answer,
        "model": model,
        "doc_ids": [d["id"] for d in hits],
        "trace_id": aiobs.current_trace_id() or "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acme People Ops Assistant → aiobs")
    parser.add_argument("question", nargs="?", help="User question")
    parser.add_argument(
        "--model",
        default=os.getenv("OLLAMA_MODEL", "gemma4:e2b"),
        help="Ollama model id",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Ask every gold question (used by portfolio_demo)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON result lines")
    args = parser.parse_args(argv)

    project_id = os.getenv("AIOBS_PROJECT_ID")
    project_slug = os.getenv("AIOBS_PROJECT_SLUG", "hr-it-assistant")
    init_kwargs: dict[str, Any] = {
        "endpoint": os.getenv("AIOBS_OTLP_ENDPOINT", "http://localhost:8000/v1/traces"),
        "service_name": os.getenv("AIOBS_SERVICE_NAME", "hr-it-assistant"),
        "instrument": ["openai"],
    }
    if project_id:
        init_kwargs["project_id"] = project_id
    else:
        init_kwargs["project_slug"] = project_slug
    aiobs.init(**init_kwargs)

    docs = load_knowledge()
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    client = OpenAI(
        base_url=f"{host}/v1",
        api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
        timeout=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300")),
    )

    if args.all:
        questions = [q for q, _ in iter_gold(docs)]
    elif args.question:
        questions = [args.question]
    else:
        parser.error("provide a question or --all")
        return 2

    try:
        for question in questions:
            result = answer_question(
                question, docs=docs, client=client, model=args.model
            )
            aiobs.flush()
            result["expected_output"] = expected_for_question(docs, question)
            if args.json:
                print(json.dumps(result, ensure_ascii=True))
            else:
                print(f"[model={args.model}] trace={result['trace_id']}")
                print(f"Q: {result['question']}")
                print(f"A: {result['answer']}")
                print()
    finally:
        aiobs.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Sanity-check imports without Ollama**

Run: `cd examples/hr_it_assistant && python -c "from kb import load_knowledge; print(len(load_knowledge()))"`  
Expected: `8`

- [ ] **Step 3: Commit**

```bash
git add examples/hr_it_assistant/main.py
git commit -m "$(cat <<'EOF'
feat: add People Ops RAG CLI with model flag and honest answers

EOF
)"
```

---

### Task 3: Rewrite `portfolio_demo.py` for MODEL1 / MODEL2

**Files:**
- Modify: `scripts/portfolio_demo.py`
- Generates: `examples/hr_it_assistant/aiobs.yaml`

**Interfaces:**
- Consumes: `examples/hr_it_assistant/main.py --model <id> --all --json`
- Env: `OLLAMA_MODEL1`, `OLLAMA_MODEL2`, `OLLAMA_HOST`, `AIOBS_BASE_URL`
- Exit: `0` when loop completes and check is `0` or `1`; non-zero on infra failure

- [ ] **Step 1: Update constants and runner**

Replace RAG paths/modes:

```python
ROOT = Path(__file__).resolve().parents[1]
SDK_DIR = ROOT / "sdk"
APP_DIR = ROOT / "examples" / "hr_it_assistant"
POLICY_PATH = APP_DIR / "aiobs.yaml"
CLI_DIR = ROOT / "cli"
```

Rename `run_rag` → `run_assistant` taking `model: str` instead of `mode`:

```python
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
```

Update dataset metadata keys: store `"model"` instead of `"mode"` (keep `doc_ids`).

- [ ] **Step 2: Update `main()` for two models + honest gate handling**

```python
parser.add_argument("--project-slug", default="hr-it-assistant")
# ...
project = ensure_project(base, args.project_slug, "Acme People Ops")
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

baseline_id = create_and_evaluate(
    ...,
    name=f"baseline-{stamp}",
    dataset_id=baseline_ds,
    model_config={"model": model1},
)
candidate_id = create_and_evaluate(
    ...,
    name=f"candidate-{stamp}",
    dataset_id=candidate_ds,
    baseline_experiment_id=baseline_id,
    model_config={"model": model2},
)
```

Gate handling at end:

```python
code = run_aiobs_check(policy, base)
if code == 0:
    print("gate passed")
    return 0
if code == 1:
    print("gate failed (regression or quality threshold)")
    return 0
print(f"aiobs check failed with unexpected exit {code}", file=sys.stderr)
return code
```

Also update module docstring to mention People Ops + MODEL1/MODEL2.

In `create_dataset_from_runs` metadata, use `run.get("model")` instead of `run.get("mode")`.

- [ ] **Step 3: Commit**

```bash
git add scripts/portfolio_demo.py
git commit -m "$(cat <<'EOF'
feat: portfolio demo compares OLLAMA_MODEL1 vs OLLAMA_MODEL2

EOF
)"
```

---

### Task 4: Docs + remove `examples/rag_faq`

**Files:**
- Create: `examples/hr_it_assistant/README.md`
- Modify: `README.md` (root portfolio section)
- Modify: `docs/02-domain-model.md` (RAG FAQ wording → People Ops / RAG QA)
- Modify: `docs/superpowers/specs/2026-10-02-hr-it-assistant-portfolio-design.md` status → Approved
- Delete: `examples/rag_faq/` (all files)

- [ ] **Step 1: Write example README**

Cover:

1. Prerequisites: compose up, `CONTENT_CAPTURE_ENABLED=true`, Ollama, pull **two** models
2. Env: `OLLAMA_MODEL1`, `OLLAMA_MODEL2`, `OLLAMA_HOST`
3. Single question command (from `sdk/` with `uv run --extra openai --with openai`)
4. Full portfolio: `python scripts/portfolio_demo.py`
5. Note: gate may pass or fail depending on models; that is expected
6. Link to design spec

- [ ] **Step 2: Update root README portfolio section**

Replace “RAG FAQ” block with People Ops + MODEL1/MODEL2, link to `examples/hr_it_assistant/README.md` and the new design spec (remove link to missing `2026-10-01-portfolio-rag-faq-design.md`).

- [ ] **Step 3: Fix `docs/02-domain-model.md` example phrase**

Change “RAG FAQ vs classification” → “People Ops RAG vs classification” (or “rag_qa vs classification”).

- [ ] **Step 4: Delete old example**

```bash
rm -rf examples/rag_faq
```

Grep to confirm no remaining path references to `examples/rag_faq` (ignore `rag-faq` string in unrelated unit tests):

```bash
rg 'examples/rag_faq|rag_faq' -g '!**/test_*.py' -g '!**/tests/**'
```

Expected: only historical mentions if any; fix stragglers in docs/README/scripts.

- [ ] **Step 5: Mark spec approved**

In the design doc header: `**Status:** Approved`

- [ ] **Step 6: Commit**

```bash
git add examples/hr_it_assistant/README.md README.md docs/02-domain-model.md \
  docs/superpowers/specs/2026-10-02-hr-it-assistant-portfolio-design.md
git add -u examples/rag_faq
git commit -m "$(cat <<'EOF'
docs: switch portfolio demo to People Ops assistant; remove rag_faq

EOF
)"
```

---

### Task 5: Manual end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Ensure stack + models**

```bash
docker compose up --build -d
ollama pull "$OLLAMA_MODEL1"   # e.g. gemma4:e2b
ollama pull "$OLLAMA_MODEL2"   # e.g. tinyllama or another weaker model
cd sdk && uv sync --extra openai --extra dev && cd ..
cd cli && uv sync && cd ..
```

- [ ] **Step 2: Single-question smoke**

```bash
cd sdk
export AIOBS_PROJECT_SLUG=hr-it-assistant
uv run --extra openai --with openai python ../examples/hr_it_assistant/main.py \
  --model "${OLLAMA_MODEL1:-gemma4:e2b}" \
  "How many PTO days do full-time employees get per year?"
```

Expected: prints answer + trace id; answer may or may not include `20 days` (honest).

- [ ] **Step 3: Full portfolio**

```bash
export OLLAMA_MODEL1=gemma4:e2b
export OLLAMA_MODEL2=tinyllama   # or your weaker model
python scripts/portfolio_demo.py
```

Expected:

- project `hr-it-assistant` created/reused
- two experiment summaries printed
- compare JSON printed
- `gate passed` or `gate failed (regression or quality threshold)`
- script exit code `0` for both gate outcomes
- UI: http://localhost:3000 project **Acme People Ops**

- [ ] **Step 4: Re-run KB unit tests**

```bash
cd examples/hr_it_assistant && python -m pytest test_kb.py -v
```

Expected: PASS

---

## Spec coverage checklist

| Spec requirement | Task |
|---|---|
| `examples/hr_it_assistant` product + English KB | 1 |
| Keyword retrieval, no embeddings | 1–2 |
| MODEL1/MODEL2 comparison, no good/degraded | 2–3 |
| No answer cheating | 2 |
| portfolio_demo + gate 0/1 both OK | 3 |
| Remove `examples/rag_faq` + doc updates | 4 |
| Manual E2E with Ollama | 5 |
| Leave unrelated `rag-faq` test fixtures | 4 (explicit non-change) |
