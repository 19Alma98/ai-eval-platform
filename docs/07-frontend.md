# Frontend Technical Specification

## Stack

- Next.js
- TypeScript
- Tailwind CSS
- React Aria Components (owned `@/components/ui` wrappers)
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

### Visual language

OpenGrade grades AI apps, so the console reads like a report card, not a widget wall:

- **Type: one family, three voices** (IBM Plex, self-hosted via `@fontsource`, no runtime
  font requests). *Serif* for page titles, section titles and verdicts; *Sans* for the
  interface; *Mono* for ids, code and raw values.
- **Colour:** warm paper neutrals, one ink-blue accent for actions, sober green / red /
  amber for status. Colour carries meaning only (status, the primary action), never decoration.
- **Verdicts are sentences.** Headlines say what happened (“One metric got worse.”), the
  line under it says why, numbers follow. Small counts are spelled out in headlines.
- **Structure with rules, not boxes.** Overview sections and scorecards are separated by
  hairlines and whitespace; bordered surfaces are kept for tables, inputs and detail panels.
  No coloured top stripes, no icons inside headings, no arrows on buttons, no ALL-CAPS
  eyebrows: section labels are sentence case.
- **Brand:** the OpenGrade mark is a score dial three-quarters full with a tick
  (`GradeMark` in `components/app-shell.tsx`).

No login/signup screens are required for v0.1. The UI assumes a trusted local or privately deployed instance.

## UX principles

The console must be understandable by someone who has never read these docs:

- **Plain language, one vocabulary.** UI copy is English only. Domain words are fixed:
  *Test set* (gold questions), *Experiment* (one app version run on a test set),
  *Metrics* (what is scored + pass thresholds), *Quality gate*, *Production* (live traffic:
  *Health*, *Live answers*, *Traces*).
- **No technical identifiers on screen.** Never render UUIDs, content hashes or raw
  evaluator kinds. Metric kinds go through `lib/metrics-catalog.ts` (label, one-line
  description, category); unknown names are humanized. The only place an ID appears is
  inside a copyable SDK code snippet.
- **Numbers people can read.** Scores use two decimals (`formatScore`), rates are
  percentages (`formatPercent`), changes are signed points (`formatDeltaPoints`).
- **Tables stay lean.** Hide columns that are empty for every row; prefer one
  summarising cell (e.g. failing metric chips) over many numeric columns.
- **Every empty state says what to do next**, with the action button or code snippet.
- **One header per page** (`components/page-header.tsx`): breadcrumbs on detail pages,
  title, one-sentence description, actions on the right.

## Information architecture

Sidebar groups (`components/app-shell.tsx`):

- **Overview**
- **Evaluate:** Test sets (`/datasets`) · Experiments (`/experiments`) · Quality gate (`/release`)
- **Monitor:** Production — one item with three tabs (`components/production-header.tsx`):
  Health (`/monitoring`) · Live answers (`/live-runs`) · Traces (`/traces`). Detail pages
  use breadcrumbs (Production › Live answers › Answer).
- **Configure:** Metrics (`/metrics`) · App configs (`/app-configs`)

Projects are managed from the project switcher (`/projects`).

## Primary screens (RAG vertical)

### Overview

`/overview?project={id}` — single payload from `GET /projects/{project_id}/overview`
(`range` preset `15m` | `1h` | `6h` | **24h** | `7d`).

- **Getting started** — four numbered steps (test set → metrics → experiment → quality gate),
  shown only while one is incomplete.
- **Status panels** — the two questions the page answers first, each a verdict headline
  (green / red / neutral), one sentence, a few supporting numbers and one primary action:
  - *Before release*: latest experiment vs its baseline (“1 metric got worse” → link to the
    comparison; otherwise → quality gate), average pass rate, test sets, metrics set.
    Hidden while there is no experiment yet (Getting started covers it).
  - *In production*: share of failing live answers in the range (same fail rule as the
    Live "Failing" filter: judge FAIL, SDK metric FAIL, or thumbs-down), questions,
    average judge score, waiting for judge.
- **Needs attention** — failing live answers (same fail rule), regressions, unreliable judges.
- **Latest experiment vs baseline** — pass rate per metric with the change in points.
- **Live quality over time** chart, only once the range has live traffic.
- **Production scores** (SDK scores / user feedback), only when some were logged.

### Test sets

List (name, version, description) and detail: questions with expected answer, source
documents as chips, required phrases; columns with no data are hidden. Import dialog lists
the expected columns and offers a CSV template. A version that already has scored
experiments is shown as *Locked* (imports create a new version).

### Experiments

- List: experiment, **metrics meeting target** (“7 of 10” with one bar segment per
  metric), status, test set, model, baseline (“Compared with”, hidden when no experiment
  has one).
- Detail:
  - *Connect your app* card with a ready SDK snippet while no answers have arrived.
  - **Results by metric** headed by the verdict (“4 of 10 metrics meet their target”),
    grouped into Answer quality / Retrieval / Performance with pass rate bars; clicking a
    metric filters the answers that failed it.
  - **Run details** strip: SDK run metrics with readable labels (errors, latency p50/p95)
    and parameters not already in the header.
  - **Answers**: every question with the metrics it failed; the side panel shows app
    answer vs expected answer, every metric verdict with the judge explanation and
    claims, retrieved documents as cards (expected ones marked, missing ones listed),
    response time / tokens, and optionally the execution trace and raw data.
  - One primary action: **Score answers** (split button: other metrics set, individual
    metrics, custom metric).
- Compare: baseline vs candidate cards, a one-line verdict (“N metrics got worse”), a
  metric table (baseline %, candidate %, change in points, verdict) and side-by-side
  answers for the selected metric.

### Quality gate

Guided form: pick candidate + baseline (preselected: the newest finished experiment and its baseline), then a *quality bar* built from the experiment's
metrics (defaults from the project metrics thresholds), latency budget and maximum allowed
drop vs baseline. The same rules can be edited as YAML or copied for CI (`opengrade check`).
The result reads “Ready to ship” / “Not ready to ship” with each rule, the actual value and
the target; failed regression rules link to the comparison.

### Production

Three tabs under one header. **Health**: latency, cost, quality trends, alarms and the
annotation queue (one empty state when the range has no production traffic; experiment
runs are not counted). **Live answers**: list with an overall verdict per answer, score chips per metric and review state; filters
All / Failing / Waiting for judge. Detail: answer, retrieved documents, judge verdicts with
one-click *Correct* / *Wrong* review, *Re-run judge*, *Add to test set*. Judge reliability
(human agreement) is in a collapsible section.

### Metrics

Metrics sets with active metric count; detail lists each metric with its description,
category, pass threshold and settings (top-k, latency budget). Sets used by experiments
are locked and edited through a new version.

### App configs

Read-only registry browser: versions, prompt / model / retrieval, aliases.

Traces are ingest/storage plumbing (OTLP); they are only shown as optional execution
steps inside an experiment answer.

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
