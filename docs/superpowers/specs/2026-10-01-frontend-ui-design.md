# Frontend UI Design — v0.1

**Status:** Draft for implementation  
**Date:** 2026-10-01  
**Related:** [`docs/07-frontend.md`](../../07-frontend.md), research synthesis (FE Observability UI), Phase 1–4 backend APIs

## Thesis

The UI is a **developer platform console** for the quality loop:

`trace → dataset → experiment → eval → release policy → CI gate`

It is not a multi-tenant SaaS shell, not an APM replacement, and not a marketing dashboard. Credibility comes from dense, scannable tools (waterfall, compare deltas, PASS/FAIL checks), not decorative cards.

## Non-goals (v0.1)

- Login / signup / SSO / RBAC screens
- Custom dashboard builder
- Session / multi-turn replay
- Prompt playground or prompt versioning UI
- Annotation queues (human review deferred to Phase 5; labels may appear read-only if present on items)
- Flamegraph / service map / multi-visualization toggle (waterfall only)
- Real-time streaming ingest UI
- Calling LLM providers from the browser

## Stack

| Layer | Choice |
|---|---|
| Framework | Next.js (App Router) + TypeScript |
| Styling | Tailwind CSS + CSS variables (design tokens) |
| Components | shadcn/ui (primitives only; no “dashboard kit” layouts) |
| Data | TanStack Query |
| Charts | Recharts for KPI sparklines / distributions; custom SVG/CSS for waterfall |
| E2E | Playwright |
| API | REST to FastAPI `/api/v1` (same origin via rewrite/proxy in dev and Compose) |

## Information architecture

### Global chrome

```text
┌─────────────────────────────────────────────────────────────┐
│ [aiobs]  Project ▾   ─────────────  Time range ▾  ↻  Theme │
├──────────┬──────────────────────────────────────────────────┤
│ Overview │  Sticky filters (when page has filters)          │
│ Traces   │  Page content                                    │
│ Datasets │                                                  │
│ Experiments                                                  │
│ Release  │                                                  │
└──────────┴──────────────────────────────────────────────────┘
```

- **Project switcher:** `GET /api/v1/projects`; persist selected `project_id` in URL (`?project=` or `/p/{id}/…`) and localStorage fallback.
- **Time range:** default last **60 minutes**; presets 15m / 1h / 6h / 24h / 7d; `start`/`end` query params on list pages. Preserve range when drilling Trace list → detail (detail ignores range for fetch-by-id but Back restores list state).
- **Refresh:** manual refresh control + subtle “Updated … ago” from TanStack Query `dataUpdatedAt` on list/overview pages.
- **Nav labels (exact):** Overview, Traces, Datasets, Experiments, Release. Lucide (or Phosphor) icons beside labels; no badges, “New”, or marketing names.
- **Icons:** one vector family only; decorative icons `aria-hidden`; icon-only controls need accessible names.
- **Toasts:** Sonner (or shadcn toaster) in root layout for mutation feedback (e.g. add-to-dataset).
- **Timestamps:** relative in tables (“2m ago”) with absolute value in tooltip / `title`.
- **No auth chrome.** Trusted network; empty state explains Compose/local usage.
- **Deferred chrome (post–v0.1):** ⌘K command palette, density toggle, breadcrumbs.
### Routes

| Route | Purpose |
|---|---|
| `/` | Redirect to `/overview` with last project |
| `/overview` | Thin KPI overview |
| `/traces` | Trace list |
| `/traces/[traceId]` | Trace detail (waterfall + sidebar) |
| `/datasets` | Dataset list |
| `/datasets/[datasetId]` | Dataset detail + items |
| `/experiments` | Experiment list |
| `/experiments/[experimentId]` | Experiment detail + summary |
| `/experiments/[experimentId]/compare` | Baseline compare |
| `/release` | Release check form + result |

All project-scoped pages require a selected project; if none, show project picker empty state.

## Design tokens

Define in `frontend/app/globals.css` (light + `.dark`). Visual target: **Data-Dense Dashboard** (observability console), not marketing SaaS.

### Theme policy — dual parity

- **Light and dark are first-class equals.** Neither is a thin invert of the other.
- Default follows `prefers-color-scheme`; user override via theme toggle persists in `localStorage` (`aiobs.theme`).
- Both themes share the same hierarchy: background → surface → surface-2 → border → muted text → foreground.
- Contrast targets (both themes): body text ≥4.5:1; interactive boundaries / non-text status ≥3:1.
- Verify every screen in both themes before calling a task done (not inferred from one mode).

### Spacing

Scale: `4, 8, 12, 16, 24, 32, 48` (px). Prefer 8px rhythm. Dense tables use row height ~36–40px. Chart/KPI strip gap `--grid-gap: 8px`.

### Radius

`sm: 4px`, `md: 6px`. No large card radii. No `rounded-full` pills for status (use small square/soft badges).

### Typography

- **UI sans:** Geist Sans (preferred) or Fira Sans — intentional sans, not Inter/Roboto/system-only as brand.
- **Mono:** Geist Mono or JetBrains Mono **only** for: trace/span IDs, JSON payloads, timestamps, raw attribute keys/values, CLI snippets.
- **Tabular numerals** on all metrics and deltas (`font-variant-numeric: tabular-nums`).
- Hierarchy: page title (`~20–24px`), section (`~16px`), body (`14px`), meta/caption (`12px`). No oversized marketing display type in-app.

### Color (semantic, restrained)

| Token | Meaning |
|---|---|
| `--status-ok` / `--status-ok-bg` | passed / improved / success (+ muted tint bg) |
| `--status-warn` / `--status-warn-bg` | degraded / caution (+ muted tint bg) |
| `--status-fail` / `--status-fail-bg` | failed / error / regression (+ muted tint bg) |
| `--status-unset` / `--status-unset-bg` | unset / unknown |
| `--accent` | single brand accent for focus/links/primary (cyan/teal `#0891B2` light / `#22D3EE` dark — not purple-indigo) |
| `--row-hover`, `--row-selected` | table / waterfall interaction surfaces |
| `--chart-1` … `--chart-5` | colorblind-friendly series (pair with line style when multi-series) |
| `--kind-llm`, `--kind-chain`, `--kind-retriever`, `--kind-tool`, `--kind-other` | muted span-kind accents (waterfall + badges) |
| `--surface`, `--surface-2`, `--border`, `--foreground`, `--muted` | neutrals (slate/zinc stack, not pure gray) |

**Reference neutrals (approximate; encode as HSL/OKLCH in CSS):**

| Role | Light | Dark |
|---|---|---|
| Background | `#F8FAFC` | `#0B1220` |
| Surface | `#FFFFFF` | `#111827` |
| Surface-2 | `#F1F5F9` | `#1F2937` |
| Border | `#E2E8F0` | `#334155` |
| Foreground | `#0F172A` | `#F8FAFC` |
| Muted text | `#64748B` | `#94A3B8` |

Rules:

- Design in monochrome; color encodes **state, span kind, or chart series only**.
- Pair every color cue with text or icon (not color-only).
- Colorblind-friendly chart series (max 5 distinct hues).
- Status badges use text + optional tinted bg token (same pattern in light and dark).
- Theme toggle in chrome; no “dark as afterthought” opacity hacks.

### Elevation

Hairline borders (`1px --border`) over multi-layer shadows. Shadows only for transient overlays (dropdown, dialog). Same elevation rules in both themes.

### Motion

- Micro only: hover/row highlight ~150ms, panel fade; no stagger on dense tables.
- Honor `prefers-reduced-motion` (disable non-essential motion).
- No confetti, glow pulses, or celebratory motion on PASS.

### Charts

- Shared axis/units conventions (ms, USD, score 0–1).
- Threshold lines when a policy threshold is in context.
- No chart junk (3D, gradient fills for decoration, excessive legends).

## Screen specs

### 1. Overview (thin)

**One question:** “Is quality/latency/cost/errors healthy for this project in the selected window?”

**Layout:** single row of **4–5 KPI strips** (not cards with icons):

1. Quality (mean score or pass rate if available; else “—” with link to Experiments)
2. Latency (p95 ms from traces when available; else “—”)
3. Cost (sum/est. if attributes present; else “—”)
4. Error rate (% traces with error status)
5. Recent regressions (count from last compare/release if cached; else link to Release)

Each KPI: label, value, click → filtered list. Optional **mini sparkline** under Latency / Error rate when ≥5 traces in window (client-side from list durations/status — no new API). If too sparse, omit sparkline (do not fake). Below: compact “Recent traces” table (10 rows) and “Latest experiments” (5 rows).
**Empty:** “No traces yet. Run the OTLP example or `docker compose` demo.”

**Avoid:** wall of metric cards, promo panels, fake “insights”.

### 2. Trace list

**API:** `GET /api/v1/projects/{project_id}/traces?status=&start=&end=&cursor=&limit=`

**Columns:** time, name, status, span count, duration (derived `end - start`), trace id (mono, truncated + copy).

**Filters:** status, time range (global). Service/model filters: show only when backend supports them; do not fake client-side filters for unsupported fields.

**Row click** → `/traces/[traceId]`.

**Keyboard:** `j`/`k` move selection, `Enter` open, `/` focus filter if present.

### 3. Trace detail (credibility screen)

**API:** `GET /api/v1/projects/{project_id}/traces/{trace_id}`

**Layout (Honeycomb/Datadog-like):**

```text
┌ Summary: name · status · duration · spans · time · [Add to dataset] ┐
├──────────────────────────────┬──────────────────────────────────────┤
│ Waterfall (virtualized)      │ Span sidebar                         │
│ tree + duration bars         │ Attributes | I/O | Events | Evals    │
└──────────────────────────────┴──────────────────────────────────────┘
```

**Summary:** name, status badge, duration, span count, start time, otel `trace_id` (copy), primary actions: **Add to dataset**, Back.

**Waterfall:**

- Pre-order span tree from `parent_span_id`.
- Row: collapse control, name, kind (muted kind color), status, duration bar scaled to trace duration.
- Duration axis ticks (0 / mid / end) above the bar column.
- Resizable split: waterfall | sidebar (shadcn `Resizable` / similar); persist ratio in `sessionStorage`.
- Click selects span (`--row-selected`); hover uses `--row-hover`.
- Search box highlights matching name/attribute substrings; prev/next match.
- Collapse/expand children. Focus-subtree (hide non-ancestors/descendants) is deferred post–v0.1.
- Virtualize when `spans.length > 200` (render window only).

**Sidebar tabs:**

1. **Attributes** — key/value table; redact indicator if value is placeholder/redacted metadata.
2. **Input / Output** — prefer span attributes commonly used for gen AI (`input`, `output`, OpenInference fields); fall back to trace-level `input`/`output` for root.
3. **Events** — list from `span.events`.
4. **Evals** — evaluation results linked to this trace/span when available; if none, empty copy “No evaluation results for this span.”

**Token/cost:** surface from span attributes when present (`llm.token_count`, cost keys, etc.); show “—” when absent — never invent numbers.

**Add to dataset:** dialog → select dataset (`GET …/datasets`) or create; `POST /api/v1/datasets/{id}/items/from-trace` with `trace_id` and optional `source_span_id`.

### 4. Datasets

**List:** `GET /api/v1/projects/{project_id}/datasets` — name, version, created, item count if available.

**Detail:** `GET /api/v1/datasets/{dataset_id}` — dense item table: id, input preview, expected, actual, source_trace_id (link to trace), metadata.

**Filters:** text search on input preview (client-side for v0.1 if list is small).

**Human review:** **out of scope** for interactive labeling in v0.1 (Phase 5). Do not ship review UI stubs that look unfinished; omit until Phase 5.

**Create dataset:** simple dialog (name, description, version).

### 5. Experiments

**List:** `GET /api/v1/projects/{project_id}/experiments` — name, status, dataset, app version, created.

**Detail:**

- Header: name, status, dataset link, baseline link, model_config summary.
- Actions: **Evaluate** (pick evaluators), **Compare to baseline**, open Release with experiment preselected.
- **Summary:** `GET /api/v1/experiments/{id}/summary` — table per evaluator: mean_score, pass_rate, n_items, n_error (tabular nums).
- **Runs:** `GET …/runs` — status, timestamps; expand for per-item results.

**Compare (`/compare`):**

- `GET /api/v1/experiments/{id}/compare/{baseline_id}`
- Aggregate table: metric, candidate, baseline, delta, status (`regression` | `improved` | `unchanged` | `unavailable`).
- Color + text for status; sort regressions first.
- No celebratory animation on improved.

**Metric distributions:** deferred post–v0.1. Summary table + compare are the v0.1 must-haves.

### 6. Release check

**API:** `POST /api/v1/projects/{project_id}/release-check`

**Form:**

- Experiment select
- Baseline experiment (required when policy includes `regression`)
- Policy: YAML or structured fields matching CLI/`aiobs.yaml` keys (`quality.min`, latency p95, cost, regression max_delta). Prefer YAML textarea that parses to `policy` object for parity with CI.

**Result (GitHub-like):**

```text
● PASS  or  ● FAIL
Experiment … · Baseline …

Checks
✓ quality.min     actual 0.91  threshold 0.85
✗ latency.p95     actual 2610  threshold 2000
```

- Each failed row links to experiment summary/compare when relevant.
- HTTP 200 with `status: failed` is a normal result, not a transport error.
- Transport/4xx errors use error state, not FAIL badge.

## Component inventory (app-level)

| Component | Responsibility |
|---|---|
| `AppShell` | Nav, project switcher, time range, refresh, theme |
| `StatusBadge` | ok/warn/fail/unset (+ tint bg) |
| `DataTable` | dense table + keyboard selection + sticky header |
| `KpiStrip` | overview metrics (+ optional sparkline) |
| `TraceWaterfall` | virtualized waterfall + kind colors + duration axis |
| `SpanSidebar` | tabs for selected span |
| `JsonBlock` | mono, copy, collapsed large trees |
| `CompareTable` | experiment deltas |
| `ReleaseResult` | PASS/FAIL checklist |
| `EmptyState` / `ErrorState` / `LoadingBlock` | operational copy only |
| `AddToDatasetDialog` | promote trace → dataset item |
| `RelativeTime` | relative label + absolute tooltip |
Prefer composition of shadcn `Button`, `Dialog`, `DropdownMenu`, `Select`, `Tabs`, `Tooltip`, `ScrollArea`. Do not import third-party admin templates.

## State & data fetching

- TanStack Query keys: `['projects']`, `['traces', projectId, filters]`, `['trace', projectId, traceId]`, `['datasets', projectId]`, `['dataset', id]`, `['experiments', projectId]`, `['experiment', id]`, `['experiment-summary', id]`, `['experiment-compare', id, baselineId]`, `['release-check', …]`.
- Mutations invalidate related lists.
- API base: `NEXT_PUBLIC_API_BASE_URL` or Next rewrite `/api/v1` → backend.
- Never call providers from the browser.

## Empty / loading / error

| State | Behavior |
|---|---|
| Loading | Skeleton lines matching table/KPI geometry (no spinners-as-page) |
| Empty | One sentence + next action (ingest trace, create dataset) |
| Error | Message + retry; show status code for 4xx/5xx |
| Sparse | Tables render with “—” for missing optional metrics |

## Accessibility

- WCAG 2.2 AA where practical: focus rings, contrast, semantic headings/tables, `prefers-reduced-motion` disables non-essential motion.
- Keyboard path for list → detail → sidebar.
- Status not conveyed by color alone.
- Dual-theme parity: re-check contrast and border visibility in **both** light and dark (borders that vanish in one theme are a defect).

## Anti-patterns (explicit reject)

- Purple/indigo gradient themes, glow, glassmorphism, emoji in chrome
- Marketing card grids / icon KPI tiles
- Confetti or motion on PASS
- Names like “Insights Hub”, “AI Cockpit”
- Shipping Overview as a fake-rich dashboard before Trace detail works
- Placeholder human-review UI with disabled buttons

## Implementation slice order

1. Scaffold `frontend/` + tokens + `AppShell` + project switcher  
2. Trace list + Trace detail (waterfall + sidebar + add-to-dataset)  
3. Experiments list/detail/summary + compare  
4. Release check UI  
5. Datasets list/detail + create  
6. Overview thin  
7. Compose service + Playwright smoke (list traces, open detail, release result render)

## Success criteria

- Demo path (~10 min): Compose up → example traces visible → inspect waterfall → add to dataset → see experiment compare → run release check in UI.
- UI reads as console-grade (density, mono IDs, semantic status), not vibe-coded SaaS.
- No auth screens; trusted-network copy in empty states / README only.

## Open follow-ups (post–v0.1)

- Human review / annotation queues (Phase 5)
- Stronger Overview aggregations if dedicated metrics endpoints appear
- Span search by attribute operators; focus-subtree in waterfall
- Flamegraph toggle; metric distribution charts on experiments
- Sessions replay when `session_id` grouping is first-class in API
- ⌘K command palette; table density toggle; breadcrumbs
- Auto-refresh intervals (beyond manual refresh)
