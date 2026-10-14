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

## Production trace scores & feedback

Branch `feat/production-trace-scores` (2026-10-14): `aiobs.log_score`, `aiobs.log_feedback`,
`aiobs.score_trace`, `@aiobs.trace(metrics=...)`, `trace_scores` table and API, Live + overview UI.

- [ ] **Sampling is nested, not independent.** `metrics_sample_rate` and `live_sample_rate` use the
  same trace-id hash, and both correlate with an OTel `TraceIdRatioBased` head sampler (effective
  rate `min(m, r)/r`). Salt the hash if independent samples are wanted.
- [ ] **`flush()` waits on a global count.** `_scores.flush` / `_production.drain` wait until the
  queue is empty, so under steady traffic they can time out even though everything queued before
  the call was sent. Use sequence numbers if per-request `flush()` (serverless) matters.
- [ ] **Captured data by reference:** queued metric jobs hold the call's args/result until scored
  (memory, and mutation after return changes what the metric sees). Consider a size guard.
- [ ] Small test gaps: multi-page `failed_only` with a trace FAIL on a later page; upper-case
  `source_trace_id` on the list path; nested `@aiobs.trace` captures with `record_documents` from
  threads the traced function starts (context not copied — document).

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

UI

Manca una pagina Traces, che in Langfuse è il cuore. Le API delle trace esistono, ma nella navigazione non c'è una lista con vista ad albero o timeline degli span. Per un RAG serve una vista dedicata: query → chunk recuperati con punteggio → prompt → risposta → claim del judge evidenziati sui chunk.

Confronto tra esperimenti alla MLflow. I grafici (recharts) ci sono solo in Overview e Live. Mancano:
- confronto di N esperimenti in tabella, con metriche come colonne e ordinamento;
- andamento delle metriche tra versioni;
diff tra item affiancati, con le domande che peggiorano o migliorano;
- filtri per parametro (modello, prompt).

Monitoraggio della produzione:
- serie temporali per metrica, con percentili di latenza, costi e token;
- distribuzione dei punteggi e soglie di allarme;
- coda di annotazione per revisione umana (il modello delle review esiste già) e promozione nel dataset in un clic.

Due modalità di build della UI. La UI viene costruita in due modi: export statico servito da FastAPI per aiobs ui, e Next standalone con un servizio web per Compose. Sono due percorsi da testare e possono divergere. Consiglio un'unica immagine con API e UI statica, la stessa servita da aiobs ui.

Collegamenti diretti. Ogni oggetto (trace, esperimento, item) deve avere un URL stabile, che l'SDK stampa a fine esecuzione.


Container e produzione

- Il punteggio viene calcolato con le BackgroundTasks di FastAPI, nello stesso processo dell'API: non scala e non è affidabile sotto carico. Serve un comando aiobs worker separato con una coda (tabella Postgres con SKIP LOCKED oppure Redis).
- Ingestione OTLP ad alto volume: scrittura in batch e conservazione dei dati con TTL.
- Immagine ufficiale su GHCR o Docker Hub, chart Helm, migrazioni come job separato.
- Telemetria anonima disattivabile, se volete misurare l'adozione.


Ordine consigliato
- Nome su PyPI, autenticazione, CLI nell'SDK, Python 3.10+.
- Pagina Traces con vista RAG, e confronto di N esperimenti.
- Metriche custom (@metric, log_score, feedback) e live automatico da @trace con campionamento.
- Worker separato, immagine unica e Helm.