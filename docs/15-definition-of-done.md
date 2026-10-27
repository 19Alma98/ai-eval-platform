# Definition of Done — MVP

The platform MVP is complete when:

- [x] `docker compose up` starts the full stack on a trusted local network.
- [x] No application-level login is required for the local demo path.
- [x] A documented Python example emits an OTLP trace.
- [x] Trace/span data is visible in the UI.
- [x] LLM/tool/retrieval spans can be inspected. — e2e `LLM, tool and retrieval spans can be inspected` in `frontend/tests/e2e/smoke.spec.ts`
- [x] Sensitive content can be disabled/redacted. — [`10-security-privacy.md`](10-security-privacy.md#content-capture-and-redaction)
- [x] A trace can become a dataset item.
- [x] At least 5 deterministic evaluators work.
- [x] At least 2 LLM-judge evaluators work through a provider adapter.
- [x] Experiments are versioned. — [`02-domain-model.md`](02-domain-model.md#versioning)
- [x] Two experiments can be compared.
- [x] A YAML release policy can be evaluated.
- [x] CLI returns correct exit codes.
- [ ] GitHub Actions example can block a release.
- [x] Unit/integration/frontend smoke tests exist. — backend/SDK pytest, frontend unit tests and Playwright smoke run in `.github/workflows/ci.yml`
- [x] README contains architecture, quickstart and demo GIF/video.
- [x] Docs state the trusted-network deployment model and that public exposure needs an external auth layer.
- [ ] Benchmark results are published.
- [x] Security/privacy limitations are documented.
- [x] Evaluator extension point is documented for contributors. — [`16-custom-evaluators.md`](16-custom-evaluators.md)
