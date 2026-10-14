# TODO

Open items from the RAG evaluation reviews (2026-10-08, 2026-10-11). Fixed items are in git history.

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


Container e produzione
- Il punteggio viene calcolato con le BackgroundTasks di FastAPI, nello stesso processo dell'API: non scala e non è affidabile sotto carico. Serve un comando aiobs worker separato con una coda (tabella Postgres con SKIP LOCKED oppure Redis).
- Ingestione OTLP ad alto volume: scrittura in batch e conservazione dei dati con TTL.


Other 
- Nome su PyPI, CLI nell'SDK, Python 3.10+.
- [ ] **Optional auth (later).** Opt-in API key / basic auth for `/api/v1/*` and `/v1/traces`
  when someone wants app-level protection without an edge layer. Not required for the
  self-hosted trusted-network model.


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
