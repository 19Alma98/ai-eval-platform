# Roadmap

Where OpenGrade is and where it is going. Releases and their changes: [changelog](changelog.md).
Contributions on any item below are welcome ([contributing](contributing.md)).

## Available today

| Area | What works |
|---|---|
| **Tracing** | OTLP/HTTP ingest with OpenInference conventions; `@og.trace` / `og.span`; auto-instrumentation for OpenAI, Anthropic, LangChain, LlamaIndex, Bedrock; users, sessions, tags, metadata; redaction and content capture switch |
| **Test sets** | Versioned datasets (`rag_qa`, `rag_chat`, `generic`) from files, dicts or DataFrames; import in the UI; promotion from production answers and conversations |
| **Metrics** | Retrieval (`hit_at_k`, `recall_at_k`, `precision_at_k`, `mrr`, `ndcg`), deterministic checks, claim-level LLM judges for RAG, conversation judges, safety classifiers, custom Python metrics and custom LLM judges |
| **Experiments** | `og.evaluate`, sweeps over a grid of configurations, repeats, groups, app config snapshots, git commit tracking |
| **Comparison and gate** | Paired bootstrap comparison with a baseline alias, per-question diffs, non-inferiority checks, statistical power warning, `opengrade evaluate` / `check` with a YAML policy, Markdown and JUnit reports |
| **Production** | Live scoring of sampled traffic, user feedback and SDK scores, session judges on conversations, health dashboards, alert rules with webhooks, retention |
| **Operations** | SQLite (`opengrade ui`) or PostgreSQL (Docker Compose, image on GHCR), API keys with `admin` / `read` / `ingest` scopes, ingest backpressure |

## Next

Ordered roughly by priority.

- **Multi-replica server.** Today background work (judge scoring, alerts, retention) runs inside
  the single API process. A job queue port with an in-process default and an optional
  PostgreSQL `SKIP LOCKED` worker would make several replicas safe and keep judges off the
  request path.
- **Online evaluation rules.** Run a judge or evaluator on a sampled subset of traces matching a
  filter (name, environment, attribute), not only on RAG question/answer interactions.
- **Trace-structure checks.** Assertions on span order, counts and errors (retriever before LLM,
  at most N tool calls) and agent trajectory evaluation beyond `tool_call_success`.
- **Span-attribute metrics.** Chart any numeric span attribute over time and use it in alert rules.
- **Judge calibration.** Cohen's kappa for judge-vs-human agreement (today: percentage
  agreement); deterministic PII patterns; per-category safety thresholds.
- **Scheduled canary runs.** Run a gold subset against the live endpoint on a schedule and alert
  on change.
- **Production views.** Group live answers by user and session, filter by SDK metric or feedback
  name, drill down from an alert to the traces that caused it, session-level alert rules.
- **Ingest keys bound to a project**, and per-project quotas.
- **High-volume OTLP.** Batched writes for continuous production traffic; columnar or object
  storage only if benchmarks justify it.

## Not planned

- A hosted SaaS, multi-tenant billing, or user accounts / SSO / RBAC: OpenGrade is self-hosted
  and identity stays with the surrounding infrastructure.
- A proprietary tracing protocol: ingest stays OpenTelemetry/OpenInference
  ([ADR-001](13-adr-001.md)).
- An oracle for open-ended agents: OpenGrade measures what you can define
  ([project overview](00-project-overview.md)).
