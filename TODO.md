# TODO

Open items from the RAG evaluation reviews (2026-10-08, 2026-10-11). Fixed items are in git history.

## Deferred

Do not block feature work. Pick these up when the trigger below each item shows up
(or an operator explicitly needs the flexibility).

### Performance

When optimizing, do N+1 batching first, then `failed_only` denormalization
(batching alone does not remove O(N) failed_only scans).

- [ ] **Live list N+1.** `ListLiveInteractions` loads scores and review per row (~3 queries ×
  page size; default 50, polled every 5s). Batch-load scores and reviews for a page.
  Fix when: list feels slow or query volume / pool wait shows up under normal browsing.
- [ ] **`failed_only` can scan the whole project** when few interactions failed (pages through all
  rows). Persist the verdict per interaction (e.g. `has_failed_score`) at scoring time and filter in
  SQL. Fix when: thousands+ interactions and the filter is used often (or empty full scans hurt).
  Do not replace with a fixed recent window — older failures must still surface.
  Trace scores now add one `list_by_trace_ids` query per *scanned* page; the denormalized verdict
  must also account for trace-score FAILs (they can arrive after the interaction).

### Production / ops

Postgres is source of truth for job state; the queue is a deployment detail. No Redis
(or other broker) in Compose or core deps — operators bring their own if they want one.

- [ ] **Pluggable job queue.** Routes/OTLP/recovery must not call FastAPI
  `BackgroundTasks` directly; call a `JobQueue.enqueue(name, payload)` port.
  Default backend: in-process (current BackgroundTasks behavior). Stable
  idempotent runners (`run_live_score`, `run_experiment_score`, …) stay the
  execution API. Optional later: Postgres `SKIP LOCKED` + `aiobs worker`,
  Redis/SQS/etc. as extras or docs (“bring your broker”), or a hook so operators
  push to their own orchestrator. Fix when: restarts drop work under load, API
  latency suffers from in-process judges, or multi-replica API needs shared queue.
- [ ] **OTLP high volume.** Batch writes and retention/TTL for traces/spans.
  Fix when: continuous production OTLP, disk growth, or ingest/query pressure.
  ClickHouse / object storage only if benchmarks justify (roadmap Phase 7).

### Auth

Trusted-network / reverse-proxy remains the default self-hosted model.

- [ ] **Optional auth.** Opt-in API key / basic auth for `/api/v1/*` and `/v1/traces`
  when someone wants app-level protection without an edge layer. Not required for
  the trusted-network model. Fix when: an operator asks for app-level auth (SSO/RBAC
  stay out of scope unless the product later owns identity).


## Other

- Nome su PyPI
- Python 3.10+.


UI

se non ho selezionato un progetto, cliccando le cose nel pannello di sinistra ("Test set", "Experiment", ...) non capita nulla. Dovrei forse gestire il click con nessun progetto selezionato perchè così sembra che non funzioni la selezione

Manca una pagina Traces, che in Langfuse è il cuore. Le API delle trace esistono, ma nella navigazione non c'è una lista con vista ad albero o timeline degli span. Per un RAG serve una vista dedicata: query → chunk recuperati con punteggio → prompt → risposta → claim del judge evidenziati sui chunk.

Confronto tra esperimenti alla MLflow. I grafici (recharts) ci sono solo in Overview e Live. Mancano:
- confronto di N esperimenti in tabella, con metriche come colonne e ordinamento;
- andamento delle metriche tra versioni;
- diff tra item affiancati, con le domande che peggiorano o migliorano;
- filtri per parametro (modello, prompt).

Monitoraggio della produzione:
- serie temporali per metrica, con percentili di latenza, costi e token;
- distribuzione dei punteggi e soglie di allarme;
- coda di annotazione per revisione umana (il modello delle review esiste già) e promozione nel dataset in un clic.

Due modalità di build della UI. La UI viene costruita in due modi: export statico servito da FastAPI per aiobs ui, e Next standalone con un servizio web per Compose. Sono due percorsi da testare e possono divergere. Consiglio un'unica immagine con API e UI statica, la stessa servita da aiobs ui.

Collegamenti diretti. Ogni oggetto (trace, esperimento, item) deve avere un URL stabile, che l'SDK stampa a fine esecuzione.
