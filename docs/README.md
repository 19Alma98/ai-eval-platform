# AI Evaluation & Observability Platform — Technical Docs

Implementation baseline for an **open-source, self-hosted** AI quality engineering platform.

Not a hosted SaaS product: the target is a reusable platform that runs in Docker/Kubernetes, speaks open telemetry standards, and plugs into CI.

**Scope:** CI regression gates for checkable AI apps (RAG, classification, structured extraction, fixed-schema tool calling). Not an oracle for open-ended agents — see fit / non-fit in `00-project-overview.md`.

Start with:
1. `00-project-overview.md`
2. `01-architecture.md`
3. `02-domain-model.md`
4. `03-evaluation-engine.md`
5. `04-tracing-and-otel.md`
6. `05-api.md`
7. `06-database.md`
8. `07-frontend.md`
9. `08-cli-ci.md`
10. `09-testing.md`
11. `10-security-privacy.md`
12. `11-roadmap.md`
13. `12-mvp-user-stories.md`

Architecture decisions:
- `13-adr-001.md`
- `14-adr-002.md`

Completion criteria:
- `15-definition-of-done.md`
