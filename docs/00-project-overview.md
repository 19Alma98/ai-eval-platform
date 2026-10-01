# AI Evaluation & Observability Platform — Technical Specification

## Status

Draft v0.1 — implementation baseline

## Platform thesis

An open-source, self-hosted platform for AI quality engineering.

This is not a hosted SaaS product. The goal is a reusable platform that teams run locally or in their own infrastructure, extend with custom evaluators, and wire into CI/CD.

The platform combines:
- OpenTelemetry/OpenInference-compatible tracing
- reusable evaluation primitives
- datasets and experiments
- human review
- regression policies
- CI/CD integration

The primary differentiator is not generic observability. The core workflow is:

Production trace → failure/example → dataset → experiment → evaluation → regression policy → CI gate.

## Goals

1. Accept AI application telemetry through an open standard.
2. Explore traces and AI-specific operations.
3. Turn traces into reusable evaluation examples.
4. Execute deterministic and LLM-based evaluators.
5. Compare experiments against baselines.
6. Express release-quality policies as code.
7. Fail CI when quality, latency, cost, or safety regressions exceed thresholds.
8. Provide a polished web UI and a CLI over the same domain concepts.
9. Run locally with Docker Compose with minimal friction.
10. Keep the domain/evaluation core independent from FastAPI.
11. Expose stable extension points (evaluators, providers, redaction, ingestion normalization).

## Non-goals for v0.1

- Building a model provider.
- Training foundation models.
- Replacing a general-purpose APM.
- Implementing a proprietary tracing protocol.
- Full distributed event streaming.
- Multi-region HA.
- Built-in authentication, SSO, or RBAC (deployment/network concern; see Security).
- Multi-tenant SaaS tenancy or billing.
- A hosted cloud offering.
- A second MCP-focused product.

## Deployment model

v0.1 assumes a **trusted network**:

- local Docker Compose for development and demos;
- self-hosted containers behind the operator’s reverse proxy, VPN, or cluster network policy when exposed beyond localhost.

Identity and access control are intentionally left to the surrounding infrastructure. The platform may later accept an optional trust boundary (for example a reverse-proxy identity header or API key), but that is not required for MVP completeness.

## Design principles

- Open-source platform first, not a closed product surface.
- Standards first.
- Evaluation before visualization.
- Provider agnostic.
- Privacy by default.
- Deterministic core; LLM judges are adapters.
- API/CLI/UI use the same domain concepts.
- Local-first developer experience.
- Extensible by design (registry/adapters, not forks of core).
- Observable by design.
- Auth is infrastructure; the platform stays usable without an identity system.
