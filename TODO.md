# TODO

Open items from the RAG evaluation reviews (2026-10-08, 2026-10-11). Fixed items are in git history.

## Before publishing on PyPI

- [ ] **Authentication.** No auth at all today. At minimum an API key for `/api/v1/*` and
  `/v1/traces`; people will expose it once it is on PyPI.

## Judge validation (meta-eval)

Synthetic runs on the 12-item HR gold set, judge `gemma4:e2b`, content-hashed prompts + format
repair (2026-10-12). Thresholds: `examples/hr_it_assistant/judge_sanity_thresholds.yaml`.

| variant | correctness | groundedness | answer_relevance | hit@k | context_recall |
|---|---|---|---|---|---|
| good | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| wrong_fact | 0.17 | 0.08 | 1.0 | 1.0 | — |
| hallucination | 1.0 | 0.58 | 0.83 | 1.0 | 1.0 |

- [ ] Run the missing **refusal** variant and the **live** mode (groundedness + answer_relevance).

## Ragas / DeepEval adapters

`aiobs.integrations.ragas` / `.deepeval` (2026-10-13) are tested only against fake modules: neither
library is installed, so `test_real_ragas_sample_accepts_our_fields` and
`test_real_deepeval_case_accepts_our_fields` are skipped.

- [ ] **Verify against the real libraries.** Install `aiobs-eval[ragas]` and `aiobs-eval[deepeval]`
  and run one real metric each end to end (e.g. `Faithfulness`, `AnswerRelevancyMetric`) with a
  local judge. Check what the fakes assume: Ragas `required_columns` format (incl. `:optional`),
  DeepEval `_required_params` / `evaluation_params`, the `a_measure` kwargs (`_show_indicator`,
  `_log_metric_to_confident`), judge model name extraction for `config["llm"]`.
- [ ] **Run the real-library tests in CI** (a job with both extras), so a library upgrade that breaks
  the mapping fails a build instead of every item turning ERROR.
- [ ] Known limits, decide if worth lifting: Ragas multi-turn metrics unsupported; DeepEval
  lower-is-better metrics (Bias, Toxicity, Hallucination, PIILeakage) rejected; `GEval` without
  `evaluation_steps` regenerates steps per item; DeepEval `context` / `tools_called` not mapped.

## Performance

Deferred until list latency, DB pool pressure, or large projects make them hurt.
Do not block feature work on these. When optimizing, do N+1 batching first, then
`failed_only` denormalization (batching alone does not remove O(N) failed_only scans).

- [ ] **Live list N+1.** `ListLiveInteractions` loads scores and review per row (~3 queries ×
  page size; default 50, polled every 5s). Batch-load scores and reviews for a page.
  Fix when: list feels slow or query volume / pool wait shows up under normal browsing.
- [ ] **`failed_only` can scan the whole project** when few interactions failed (pages through all
  rows). Persist the verdict per interaction (e.g. `has_failed_score`) at scoring time and filter in
  SQL. Fix when: thousands+ interactions and the filter is used often (or empty full scans hurt).
  Do not replace with a fixed recent window — older failures must still surface.
  Trace scores now add one `list_by_trace_ids` query per *scanned* page; the denormalized verdict
  must also account for trace-score FAILs (they can arrive after the interaction).



Altro:

- serve un AsyncClient, perché molte app RAG sono async;
- oggetti Dataset da pandas, HuggingFace, CSV, iterabili;
- annotare sessioni e utenti (session_id, user_id) per raggruppare le conversazioni.

## UI

- [x] **Pagina Traces.** `/traces`: lista con filtri (stato, intervallo, ricerca su nome / trace / sessione / utente)
  e paginazione a cursore (`GET /projects/{id}/traces`). `/traces/{trace_id}`: vista RAG
  (query → chunk recuperati con punteggio, per stadio retriever / reranker → prompt → risposta →
  claim del giudice evidenziati sui chunk) e timeline ad albero degli span.
- [x] **Confronto esperimenti alla MLflow.** `/experiments/compare`: N esperimenti in tabella con le
  metriche come colonne e ordinamento, filtri per modello, prompt, test set e qualsiasi parametro di
  `model_config`, andamento delle metriche tra versioni. Selezionandone due si apre il diff domanda per
  domanda, ora filtrabile su "peggiorate" / "migliorate". API: `GET /projects/{id}/experiments/summaries`.
- [x] **Monitoraggio della produzione.** `/monitoring`: serie temporali con percentili di latenza
  (p50/p90/p99), token e costi, distribuzione dei punteggi per metrica con soglia di pass, soglie di
  allarme sul fail rate, coda di annotazione (`live-interactions?unreviewed_only=true`) con review e
  promozione nel test set dalla coda. API: `GET /projects/{id}/monitoring`.
  - [ ] Le soglie di allarme stanno nel browser (localStorage, per progetto): portarle sul server
    se servono notifiche (email / webhook) o condivisione tra utenti.
  - [ ] Il monitoraggio legge fino a 5000 trace per finestra in memoria; per volumi alti servono
    aggregati in SQL o tabelle di rollup (vedi ingestione OTLP ad alto volume).
- [x] **Una sola build della UI.** Solo export statico (`npm run build`), servito da FastAPI sia da
  `aiobs ui` sia dall'immagine Docker (`backend/Dockerfile` costruisce la UI in uno stage Node).
  Compose non ha più il servizio `web`: UI e API su http://localhost:8000. `npm run dev` resta per
  sviluppare la UI (proxy verso `API_ORIGIN`).
- [x] **Collegamenti diretti.** URL stabili: `/traces/{trace_id}`, `/experiments/{id}`,
  `/experiments/{id}?item={dataset_item_id}` (la selezione dell'item è nell'URL), con `?project=`.
  L'SDK espone `result.url`, `item.url`, `item.trace_url`, li elenca in `result.summary()` e stampa il
  link a fine esecuzione su stderr (`AIOBS_QUIET=1` per silenziarlo).

Container e produzione

- Il punteggio viene calcolato con le BackgroundTasks di FastAPI, nello stesso processo dell'API: non scala e non è affidabile sotto carico. Serve un comando aiobs worker separato con una coda (tabella Postgres con SKIP LOCKED oppure Redis).
- Ingestione OTLP ad alto volume: scrittura in batch e conservazione dei dati con TTL.
- Immagine ufficiale su GHCR o Docker Hub, chart Helm, migrazioni come job separato.
- Telemetria anonima disattivabile, se volete misurare l'adozione.



- Nome su PyPI, autenticazione, CLI nell'SDK, Python 3.10+.
- Worker separato, immagine unica e Helm.