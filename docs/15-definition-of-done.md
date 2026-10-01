# Definition of Done — MVP

The platform MVP is complete when:

- [ ] `docker compose up` starts the full stack on a trusted local network.
- [ ] No application-level login is required for the local demo path.
- [ ] A documented Python example emits an OTLP trace.
- [ ] Trace/span data is visible in the UI.
- [ ] LLM/tool/retrieval spans can be inspected.
- [ ] Sensitive content can be disabled/redacted.
- [ ] A trace can become a dataset item.
- [ ] At least 5 deterministic evaluators work.
- [ ] At least 2 LLM-judge evaluators work through a provider adapter.
- [ ] Experiments are versioned.
- [ ] Two experiments can be compared.
- [ ] A YAML release policy can be evaluated.
- [ ] CLI returns correct exit codes.
- [ ] GitHub Actions example can block a release.
- [ ] Unit/integration/frontend smoke tests exist.
- [ ] README contains architecture, quickstart and demo GIF/video.
- [ ] Docs state the trusted-network deployment model and that public exposure needs an external auth layer.
- [ ] Benchmark results are published.
- [ ] Security/privacy limitations are documented.
- [ ] Evaluator extension point is documented for contributors.
