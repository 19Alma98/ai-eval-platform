# Frontend Technical Specification

## Stack

- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- TanStack Query
- ECharts/Recharts
- Playwright

## Visual direction

Reference principles:
- Linear-like density
- Vercel-like typography/spacing
- observability-grade charts
- restrained color usage
- dark/light themes
- keyboard-first navigation

The UI should feel like a developer platform console, not an admin template or multi-tenant SaaS product shell.

No login/signup screens are required for v0.1. The UI assumes a trusted local or privately deployed instance.

## Primary screens (RAG vertical)

Navigation strip for RAG projects:

`Test set → App configs → Metriche → Runs → Confronta → Release`

- **Test set** — create/import `rag_qa` items (`question`, expected answer, `expected_doc_ids`); versioned datasets.
- **Metriche** — versioned metrics sets per project (`/metrics`, `/metrics/[metricsSetId]`): list with “Default progetto” badge, create set seeded from the project default pack, detail editor (enable/threshold/remove custom entries), and “Crea versione N+1” when a set is referenced. Empty projects use `POST …/metrics-pack/ensure` then refetch. Legacy pack API remains for ensure/alias compatibility.
- **Runs** — experiments pinned to a dataset version; per-item scores and execution detail (retrieve/generate timeline from bound traces).
- **Confronta** / **Release** — compare runs on the same dataset+version; CI gate uses pack metric names.

Traces remain available for debugging but are not the primary loop step.

### 1. Overview

Setup checklist: test set present, metrics pack configured, at least one scored run. Aggregate metrics reflect pack evaluators where available.

### 2. Trace Explorer

Features:
- waterfall
- span tree
- attributes
- input/output with redaction indicators
- token/cost metrics
- evaluation results

### 3. Test set (datasets)

Features:
- `rag_qa` gold fields and import (CSV/JSON)
- item list with expected doc ids
- add-from-trace (secondary; not the RAG primary path)

### 4. Runs (experiments)

Features:
- run status and pack scoring (`evaluate-pack`)
- per-item results and bound trace timeline
- baseline comparison on the same test set version
- regression markers
- create dialog binds **App config** as a peer field to Dataset (alias or family@version); free-form model/version sits under Advanced when no registry config is selected
- run detail shows a read-only **App config snapshot** (prompt, model, retrieval, content hash) when the experiment was created from a registry config

### 5. App configs (`/app-configs`)

Project-scoped registry UI (requires `projectId` query param like other console routes):

- **`/app-configs`** — list config families (latest version per name); no create in the console
- **`/app-configs/[name]`** — version history for one family, alias pins, read-only prompt/model/retrieval shown as plain text (not JSON editors)

Versions are registered from the evaluated app via SDK/API (or demo scripts). The console is for browsing, alias management, and binding configs when creating experiments.

Experiment create prefers binding `app_config_id` or `app_config_alias` (peer to dataset) over free-form `model_config`.

### 6. Release Check

A GitHub-like result:
- PASS/FAIL
- failed checks
- delta
- threshold
- link to affected samples

## Design system

Define:
- spacing scale
- typography
- status semantics
- chart conventions
- empty states
- loading states
- error states

Avoid excessive dashboard cards.

## Accessibility

Target WCAG 2.2 AA where practical:
- keyboard navigation
- focus states
- semantic controls
- contrast
- reduced motion
