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

The primary differentiator is not generic observability. For **RAG / FAQ** evaluations, the primary workflow is **dataset-first**:

Project → test set (`rag_qa` gold) → project metrics pack → SDK-bound runs → score with pack → compare / release gate.

Trace-first promotion (production trace → dataset item) remains supported for other task types and debugging, but the RAG vertical product narrative starts from a fixed exam and grading rules.

Generic loop (still valid for classification, tool schemas, and trace curation):

Trace or example → dataset → experiment/run → evaluation → regression policy → CI gate.

This is a **CI quality gate for AI apps**, not a general-purpose agent oracle.
MLflow-style metrics work when outputs are scorable against a curated dataset.
The same assumption applies here: the platform measures regressions and improvements
when “good” can be defined with ground truth, schemas, or stable judge criteria.

## What this is good for

Primary fit — applications where outputs are **narrow and checkable**:

- **RAG / FAQ** with known answers or citation constraints
- **Classification** and labeling into a fixed label set
- **Extraction** into structured fields (JSON, entities, forms)
- **Tool calling with a fixed schema** (correct tool, valid args, success/failure)
- **Latency, cost, and error-rate** regressions across app versions
- Promoting real production failures into a golden dataset and blocking releases that regress on it

Secondary fit (use carefully):

- LLM-as-judge metrics (relevance, groundedness, correctness) as **noisy signals**,
  versioned and thresholded — not as sole release truth without human review

## What this is not for (v0.1)

Out of product fit — not merely “not built yet”:

- Open-ended agents (coding agents, free-form multi-turn assistants) where success
  is subjective and hard to score reproducibly
- Claiming absolute quality scores or “the agent got smarter” without a curated dataset
- Replacing online production monitoring / APM for live traffic incidents
- Automatic discovery of all failure modes without human curation of examples
- Enterprise multi-tenant SaaS with built-in SSO/RBAC (see Non-goals and Security)

If your agent’s definition of success cannot be expressed as dataset examples +
evaluators + thresholds, this platform will not invent that definition for you.

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

Product / engineering non-goals (complement the fit section above):

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
- Guaranteeing eval quality for open-ended or highly subjective agent tasks.

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
