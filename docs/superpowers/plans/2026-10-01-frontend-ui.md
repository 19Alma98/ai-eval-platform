# Frontend UI v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a console-grade Next.js UI that covers the quality loop (traces → datasets → experiments → release check) against the existing FastAPI backend, matching [`docs/superpowers/specs/2026-10-01-frontend-ui-design.md`](../specs/2026-10-01-frontend-ui-design.md).

**Architecture:** Next.js App Router SPA-style pages call FastAPI via same-origin rewrites (`/api/v1/*` → backend). TanStack Query owns server state; URL + localStorage own project and time range. Feature folders under `frontend/features/` own screen logic; `frontend/components/` holds shared chrome/primitives.

**Tech Stack:** Next.js 15, React 19, TypeScript, Tailwind CSS 4 (or 3 if scaffold defaults), shadcn/ui, Lucide, Sonner, TanStack Query v5, Recharts, Playwright, Node 22.

## Global Constraints

- No auth/login screens; trusted-network deployment only.
- Domain copy only: Overview, Traces, Datasets, Experiments, Release (exact labels).
- No purple/indigo gradient themes, glow, glassmorphism, emoji chrome, confetti.
- Color only for semantic status, span kind, and chart series; pair with text.
- **Dual-theme parity:** light and dark are first-class; verify both before marking a task done.
- Mono font only for IDs, JSON, timestamps, raw attributes.
- UI never calls LLM providers; only FastAPI.
- Human review / annotation queues out of scope (Phase 5).
- Waterfall only (no flamegraph).
- Follow design tokens in the FE UI design spec.
- Prefer Next rewrite proxy over browser CORS (backend currently has no CORSMiddleware).

---

## File map (create unless noted)

```text
frontend/
  package.json
  next.config.ts
  tsconfig.json
  components.json          # shadcn
  playwright.config.ts
  Dockerfile
  app/
    globals.css
    layout.tsx
    providers.tsx
    page.tsx
    overview/page.tsx
    traces/page.tsx
    traces/[traceId]/page.tsx
    datasets/page.tsx
    datasets/[datasetId]/page.tsx
    experiments/page.tsx
    experiments/[experimentId]/page.tsx
    experiments/[experimentId]/compare/page.tsx
    release/page.tsx
  components/
    ui/                    # shadcn primitives
    app-shell.tsx
    status-badge.tsx
    data-table.tsx
    kpi-strip.tsx
    empty-state.tsx
    error-state.tsx
    loading-block.tsx
    json-block.tsx
    project-switcher.tsx
    time-range-picker.tsx
    theme-toggle.tsx
    relative-time.tsx
    refresh-control.tsx
  features/traces/
    trace-list.tsx
    trace-waterfall.tsx
    span-sidebar.tsx
    add-to-dataset-dialog.tsx
    build-span-tree.ts
    use-traces.ts
  features/datasets/
    dataset-list.tsx
    dataset-detail.tsx
    use-datasets.ts
  features/experiments/
    experiment-list.tsx
    experiment-detail.tsx
    compare-table.tsx
    use-experiments.ts
  features/release/
    release-check-form.tsx
    release-result.tsx
    use-release.ts
  features/overview/
    overview-dashboard.tsx
  lib/
    cn.ts
    format.ts
    time-range.ts
    project-store.ts
    api/client.ts
    api/types.ts
    api/projects.ts
    api/traces.ts
    api/datasets.ts
    api/experiments.ts
    api/evaluators.ts
    api/release.ts
  tests/e2e/smoke.spec.ts
docker-compose.yml         # modify: add web service
docs/07-frontend.md        # modify: link to design spec
```

---

### Task 1: Scaffold Next.js app + tooling

**Files:**
- Create: `frontend/package.json`, `frontend/next.config.ts`, `frontend/tsconfig.json`, `frontend/app/layout.tsx`, `frontend/app/page.tsx`, `frontend/app/globals.css`, `frontend/app/providers.tsx`, `frontend/lib/cn.ts`
- Test: `frontend` typecheck script

**Interfaces:**
- Produces: runnable `npm run dev` on `:3000`; rewrite `/api/:path*` → `http://localhost:8000/api/:path*` and `/health` → backend

- [ ] **Step 1: Create Next.js TypeScript app in `frontend/`**

```bash
cd /home/alessandromagliola/myworks/ai_eval_platform
npx create-next-app@15.5.4 frontend --typescript --tailwind --eslint --app --src-dir=false --import-alias="@/*" --turbopack --yes
```

Expected: `frontend/` with App Router.

- [ ] **Step 2: Set API rewrites in `frontend/next.config.ts`**

```ts
import type { NextConfig } from "next";

const apiOrigin = process.env.API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
      { source: "/health", destination: `${apiOrigin}/health` },
    ];
  },
};

export default nextConfig;
```

- [ ] **Step 3: Add shared `cn` helper**

```ts
// frontend/lib/cn.ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

```bash
cd frontend && npm install clsx tailwind-merge @tanstack/react-query recharts js-yaml && npm install -D @types/js-yaml playwright @playwright/test
```

- [ ] **Step 4: Add Query + theme providers**

```tsx
// frontend/app/providers.tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: { staleTime: 15_000, refetchOnWindowFocus: false, retry: 1 },
    },
  }));
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
```

Wire in `app/layout.tsx` (Geist fonts via `next/font/google` or `geist` package; body classes for light/dark).

- [ ] **Step 5: Redirect `/` → `/overview`**

```tsx
// frontend/app/page.tsx
import { redirect } from "next/navigation";
export default function Home() {
  redirect("/overview");
}
```

- [ ] **Step 6: Verify typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: PASS (or only unused-file noise until pages exist — fix any errors).

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "chore(frontend): scaffold Next.js app with API rewrites"
```

---

### Task 2: Design tokens + shadcn primitives + AppShell

**Files:**
- Create: `frontend/app/globals.css` (tokens), `frontend/components/app-shell.tsx`, `frontend/components/project-switcher.tsx`, `frontend/components/time-range-picker.tsx`, `frontend/components/theme-toggle.tsx`, `frontend/components/refresh-control.tsx`, `frontend/components/relative-time.tsx`, `frontend/components/status-badge.tsx`, `frontend/components/empty-state.tsx`, `frontend/components/error-state.tsx`, `frontend/components/loading-block.tsx`, `frontend/lib/project-store.ts`, `frontend/lib/time-range.ts`, `frontend/lib/format.ts`, `frontend/lib/api/client.ts`, `frontend/lib/api/types.ts`, `frontend/lib/api/projects.ts`
- Create: shadcn `button`, `dialog`, `dropdown-menu`, `select`, `tabs`, `tooltip`, `scroll-area`, `input`, `textarea`, `separator`, `badge`, `sonner`, `resizable`
- Modify: `frontend/app/layout.tsx`, `frontend/app/providers.tsx`

**Interfaces:**
- Consumes: Task 1 scaffold
- Produces:
  - `apiGet<T>(path)`, `apiPost<T>(path, body)` in `lib/api/client.ts`
  - `listProjects(): Promise<Project[]>`
  - `useProjectId(): { projectId: string | null; setProjectId(id: string): void }`
  - `useTimeRange(): { start: Date; end: Date; preset: string; setPreset(p: string): void }`
  - `useTheme(): { theme: "light" | "dark"; setTheme(t): void }` with `localStorage` `aiobs.theme` + `prefers-color-scheme` default
  - `AppShell` wrapping all pages (nav icons via Lucide)
  - Root `<Toaster />` (Sonner)

- [ ] **Step 1: Write failing unit-style test for time-range presets**

```ts
// frontend/lib/time-range.test.ts
import { assert, describe, it } from "node:test";
import { rangeFromPreset } from "./time-range";

describe("rangeFromPreset", () => {
  it("returns ~60 minutes for 1h", () => {
    const now = new Date("2026-10-01T12:00:00.000Z");
    const { start, end } = rangeFromPreset("1h", now);
    assert.equal(end.toISOString(), now.toISOString());
    assert.equal(start.toISOString(), "2026-10-01T11:00:00.000Z");
  });
});
```

- [ ] **Step 2: Run test — expect fail**

```bash
cd frontend && node --import tsx --test lib/time-range.test.ts
```

```bash
cd frontend && npm i -D tsx
```

Expected: FAIL module not found for `./time-range` until Step 3.

- [ ] **Step 3: Implement tokens + time-range + format + api client**

`globals.css` must define **parity tokens for light (`:root`) and `.dark`** (slate/zinc stack). Include at minimum:

```css
:root {
  /* Neutrals — light */
  --background: 210 40% 98%;
  --foreground: 222 47% 11%;
  --surface: 0 0% 100%;
  --surface-2: 210 40% 96%;
  --border: 214 32% 91%;
  --muted: 215 16% 47%;
  --row-hover: 210 40% 96%;
  --row-selected: 199 89% 94%;
  /* Accent — cyan/teal (not purple/indigo) */
  --accent: 191 91% 37%;
  /* Status + tinted backgrounds */
  --status-ok: 142 60% 35%;
  --status-ok-bg: 142 60% 95%;
  --status-warn: 38 90% 40%;
  --status-warn-bg: 38 90% 94%;
  --status-fail: 0 70% 45%;
  --status-fail-bg: 0 70% 96%;
  --status-unset: 215 14% 50%;
  --status-unset-bg: 210 20% 96%;
  /* Chart series + span kinds */
  --chart-1: 199 89% 40%;
  --chart-2: 142 60% 35%;
  --chart-3: 38 90% 40%;
  --chart-4: 280 50% 45%;
  --chart-5: 215 16% 47%;
  --kind-llm: 199 89% 40%;
  --kind-chain: 215 16% 47%;
  --kind-retriever: 142 50% 38%;
  --kind-tool: 38 80% 42%;
  --kind-other: 215 14% 50%;
  --radius-sm: 4px;
  --radius-md: 6px;
}

.dark {
  --background: 222 47% 7%;
  --foreground: 210 40% 98%;
  --surface: 222 47% 11%;
  --surface-2: 217 33% 17%;
  --border: 215 19% 35%;
  --muted: 215 20% 65%;
  --row-hover: 217 33% 14%;
  --row-selected: 199 50% 18%;
  --accent: 189 94% 55%;
  --status-ok: 142 60% 45%;
  --status-ok-bg: 142 40% 14%;
  --status-warn: 38 90% 50%;
  --status-warn-bg: 38 50% 14%;
  --status-fail: 0 70% 55%;
  --status-fail-bg: 0 50% 14%;
  --status-unset: 215 14% 60%;
  --status-unset-bg: 217 20% 16%;
  --chart-1: 189 94% 55%;
  --chart-2: 142 60% 45%;
  --chart-3: 38 90% 50%;
  --chart-4: 280 50% 65%;
  --chart-5: 215 20% 65%;
  --kind-llm: 189 94% 55%;
  --kind-chain: 215 20% 65%;
  --kind-retriever: 142 50% 50%;
  --kind-tool: 38 80% 55%;
  --kind-other: 215 14% 60%;
}
```

Verify contrast of foreground/muted on both backgrounds (≥4.5:1 body). Map shadcn CSS variables to these tokens (do not leave default violet theme).

```ts
// frontend/lib/time-range.ts
export type Preset = "15m" | "1h" | "6h" | "24h" | "7d";

const MS: Record<Preset, number> = {
  "15m": 15 * 60_000,
  "1h": 60 * 60_000,
  "6h": 6 * 60 * 60_000,
  "24h": 24 * 60 * 60_000,
  "7d": 7 * 24 * 60 * 60_000,
};

export function rangeFromPreset(preset: Preset, now = new Date()) {
  return { start: new Date(now.getTime() - MS[preset]), end: now, preset };
}
```

```ts
// frontend/lib/api/client.ts
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json() as Promise<T>;
}
```

```ts
// frontend/lib/api/types.ts
export type Project = {
  id: string;
  name: string;
  slug: string;
  created_at: string;
};
```

```ts
// frontend/lib/api/projects.ts
import { apiGet } from "./client";
import type { Project } from "./types";

export function listProjects() {
  return apiGet<Project[]>("/api/v1/projects");
}
```

Project store: read/write `localStorage` key `aiobs.projectId`; expose React hook syncing to `?project=` search param.

Also implement `formatRelativeTime` / `RelativeTime` (relative label + absolute `title`) and `RefreshControl` (calls query `refetch`, shows “Updated … ago” from `dataUpdatedAt`).

- [ ] **Step 4: Init shadcn and add primitives**

```bash
cd frontend && npx shadcn@latest init -y -d
npx shadcn@latest add button dialog dropdown-menu select tabs tooltip scroll-area input textarea separator badge sonner resizable
npm install lucide-react
```

Do **not** add `dashboard-01` block as-is — compose AppShell manually.

Wire `<Toaster />` once in `app/layout.tsx` (or providers), not per page.

- [ ] **Step 5: Implement `AppShell` with nav labels exactly: Overview, Traces, Datasets, Experiments, Release**

```tsx
const NAV = [
  { href: "/overview", label: "Overview", icon: LayoutDashboard },
  { href: "/traces", label: "Traces", icon: GitBranch },
  { href: "/datasets", label: "Datasets", icon: Database },
  { href: "/experiments", label: "Experiments", icon: FlaskConical },
  { href: "/release", label: "Release", icon: ShieldCheck },
] as const;
```

Dense left nav (~200px), top bar with project switcher + time range + refresh + theme toggle. Lucide icons; no badges. Theme: dual parity — class `.dark` on `<html>`, persist `aiobs.theme`.

- [ ] **Step 6: Create placeholder pages that use AppShell**

Each of `/overview`, `/traces`, `/datasets`, `/experiments`, `/release` renders shell + `<EmptyState title="…" />` temporarily. Spot-check light **and** dark.

- [ ] **Step 7: Re-run time-range test**

```bash
cd frontend && node --import tsx --test lib/time-range.test.ts
```

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add frontend
git commit -m "feat(frontend): dual-theme tokens, API client, and AppShell"
```

---

### Task 3: Trace list

**Files:**
- Create: `frontend/lib/api/traces.ts`, `frontend/features/traces/use-traces.ts`, `frontend/features/traces/trace-list.tsx`, `frontend/components/data-table.tsx`
- Modify: `frontend/app/traces/page.tsx`, `frontend/lib/api/types.ts`

**Interfaces:**
- Consumes: `apiGet`, project id, time range
- Produces:
  - `listTraces(projectId, { status?, start?, end?, cursor?, limit? }) → TraceListResponse`
  - Types: `TraceSummary`, `TraceListResponse`

- [ ] **Step 1: Add types + API function**

```ts
export type TraceSummary = {
  trace_id: string;
  name: string;
  status: string;
  start_time: string;
  end_time: string | null;
  span_count: number;
};

export type TraceListResponse = {
  items: TraceSummary[];
  next_cursor: string | null;
};

export function listTraces(
  projectId: string,
  q: { status?: string; start?: string; end?: string; cursor?: string; limit?: number },
) {
  const params = new URLSearchParams();
  if (q.status) params.set("status", q.status);
  if (q.start) params.set("start", q.start);
  if (q.end) params.set("end", q.end);
  if (q.cursor) params.set("cursor", q.cursor);
  if (q.limit) params.set("limit", String(q.limit));
  const qs = params.toString();
  return apiGet<TraceListResponse>(
    `/api/v1/projects/${projectId}/traces${qs ? `?${qs}` : ""}`,
  );
}
```

- [ ] **Step 2: Write Playwright stub that will fail until list works** (skip full E2E until Task 8 if backend not up — instead add a pure duration helper test)

```ts
// frontend/lib/format.test.ts
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { formatDurationMs } from "./format";

describe("formatDurationMs", () => {
  it("formats milliseconds", () => {
    assert.equal(formatDurationMs(1250), "1.25s");
    assert.equal(formatDurationMs(40), "40ms");
  });
});
```

Implement `formatDurationMs`, `formatTs`, `truncateId` in `lib/format.ts`.

- [ ] **Step 3: Implement `TraceList` dense table**

Columns: time (`RelativeTime`), name, status (`StatusBadge` with tint bg), spans, duration (`end_time - start_time`), trace id (mono truncated + copy button). Row navigates to `/traces/{traceId}?project=…`. Hover/selected use `--row-hover` / `--row-selected`. Keyboard: j/k + Enter. Sticky filter bar for status (segmented or select) + preserve time range from chrome. Wire `RefreshControl` to the traces query.

Empty copy: `No traces yet. Run the OTLP example against this project.`

Spot-check table borders and status badges in **light and dark**.

- [ ] **Step 4: Wire `/traces` page**

Require project; if missing show empty state to pick an existing project or create one via `POST /api/v1/projects` (name + slug).

- [ ] **Step 5: Manual smoke with backend**

```bash
# terminal A
cd backend && uv run uvicorn aiobs.main:app --reload --port 8000
# terminal B
cd frontend && npm run dev
curl -s http://localhost:3000/api/v1/projects | head
```

Expected: JSON projects through rewrite; Trace list loads.

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat(frontend): trace list with filters and dense table"
```

---

### Task 4: Trace detail — waterfall + sidebar + add-to-dataset

**Files:**
- Create: `frontend/features/traces/build-span-tree.ts`, `frontend/features/traces/trace-waterfall.tsx`, `frontend/features/traces/span-sidebar.tsx`, `frontend/features/traces/add-to-dataset-dialog.tsx`, `frontend/components/json-block.tsx`
- Modify: `frontend/lib/api/traces.ts`, `frontend/lib/api/datasets.ts` (create), `frontend/app/traces/[traceId]/page.tsx`

**Interfaces:**
- Consumes: `TraceDetailResponse` from `GET /api/v1/projects/{id}/traces/{traceId}`
- Produces:
  - `getTrace(projectId, traceId)`
  - `buildSpanTree(spans) → SpanNode[]` (pre-order, children arrays)
  - `AddToDatasetDialog` → `POST /api/v1/datasets/{datasetId}/items/from-trace`

- [ ] **Step 1: Failing test for span tree**

```ts
// frontend/features/traces/build-span-tree.test.ts
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildSpanTree, flattenVisible } from "./build-span-tree";

describe("buildSpanTree", () => {
  it("nests by parent_span_id", () => {
    const spans = [
      { span_id: "a", parent_span_id: null, name: "root", kind: "CHAIN", start_time: "2026-01-01T00:00:00Z", end_time: "2026-01-01T00:00:02Z", status: "ok", attributes: {}, events: [] },
      { span_id: "b", parent_span_id: "a", name: "child", kind: "LLM", start_time: "2026-01-01T00:00:00.5Z", end_time: "2026-01-01T00:00:01.5Z", status: "ok", attributes: {}, events: [] },
    ];
    const tree = buildSpanTree(spans);
    assert.equal(tree.length, 1);
    assert.equal(tree[0].span.span_id, "a");
    assert.equal(tree[0].children[0].span.span_id, "b");
    assert.equal(flattenVisible(tree, new Set()).length, 2);
  });
});
```

- [ ] **Step 2: Run — expect fail**

```bash
cd frontend && node --import tsx --test features/traces/build-span-tree.test.ts
```

- [ ] **Step 3: Implement tree builder + waterfall**

Waterfall requirements from spec:

- Duration bar scaled to trace `end - start`
- Duration axis ticks (0 / mid / end) above the bar column
- Span kind muted color via `--kind-*` tokens (LLM / CHAIN / RETRIEVER / TOOL / other)
- Collapse/expand; search highlight; select span (`--row-selected`)
- Resizable split waterfall | sidebar (shadcn `Resizable`); persist ratio in `sessionStorage`
- Virtualize when `spans.length > 200` (windowed list over flattened visible rows)

Sidebar tabs: Attributes | Input / Output | Events | Evals (empty state OK).

`JsonBlock`: mono, copy, collapse when stringified length > 4k chars.

Token/cost: read known attribute keys if present; else show "—".

On successful add-to-dataset: `toast.success(…)` via Sonner.

Verify waterfall + sidebar in both themes.

- [ ] **Step 4: Add-to-dataset dialog**

```ts
// frontend/lib/api/datasets.ts
export function listDatasets(projectId: string) {
  return apiGet<Dataset[]>(`/api/v1/projects/${projectId}/datasets`);
}
export function createDataset(projectId: string, body: { name: string; description?: string; version?: number }) {
  return apiPost<Dataset>(`/api/v1/projects/${projectId}/datasets`, body);
}
export function addItemFromTrace(datasetId: string, body: { trace_id: string; source_span_id?: string; expected_output?: unknown; metadata?: Record<string, unknown> }) {
  return apiPost<DatasetItem>(`/api/v1/datasets/${datasetId}/items/from-trace`, body);
}
```

- [ ] **Step 5: Pass tree test**

```bash
cd frontend && node --import tsx --test features/traces/build-span-tree.test.ts
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat(frontend): trace detail waterfall, sidebar, add-to-dataset"
```

---

### Task 5: Datasets list + detail

**Files:**
- Create: `frontend/features/datasets/use-datasets.ts`, `frontend/features/datasets/dataset-list.tsx`, `frontend/features/datasets/dataset-detail.tsx`
- Modify: `frontend/app/datasets/page.tsx`, `frontend/app/datasets/[datasetId]/page.tsx`

**Interfaces:**
- Consumes: datasets API from Task 4
- Produces: list + detail pages; create dataset dialog; `source_trace_id` links to `/traces/{id}`

- [ ] **Step 1: Implement list + create dialog** (name, description, version default 1)

- [ ] **Step 2: Implement detail table** — columns: id (truncated), input preview, expected, actual, source_trace_id link, metadata keys count

- [ ] **Step 3: Client-side filter** on input preview text

- [ ] **Step 4: Manual check** create dataset + open detail after add-from-trace

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): datasets list and detail"
```

---

### Task 6: Experiments list, detail, summary, compare

**Files:**
- Create: `frontend/lib/api/experiments.ts`, `frontend/lib/api/evaluators.ts`, `frontend/features/experiments/use-experiments.ts`, `frontend/features/experiments/experiment-list.tsx`, `frontend/features/experiments/experiment-detail.tsx`, `frontend/features/experiments/compare-table.tsx`
- Modify: experiment app routes

**Interfaces:**
- Produces:
  - `listExperiments(projectId)`
  - `getExperiment(id)`
  - `summarizeExperiment(id)`
  - `compareExperiments(id, baselineId)`
  - `evaluateExperiment(id, { evaluator_ids })`
  - `listEvaluators(projectId)`
  - `CompareTable` sorting regressions first; status text + color

- [ ] **Step 1: API module**

```ts
export function compareExperiments(experimentId: string, baselineId: string) {
  return apiGet<ExperimentCompareResponse>(
    `/api/v1/experiments/${experimentId}/compare/${baselineId}`,
  );
}
```

Types mirror `ExperimentCompareResponse` / `MetricComparisonResponse` in `backend/src/aiobs/api/schemas.py`.

- [ ] **Step 2: Compare table unit helper**

```ts
// frontend/features/experiments/sort-metrics.ts
export function sortMetricsForDisplay<T extends { status: string }>(metrics: T[]): T[] {
  const rank: Record<string, number> = {
    regression: 0,
    unavailable: 1,
    unchanged: 2,
    improved: 3,
  };
  return [...metrics].sort(
    (a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9),
  );
}
```

```ts
// frontend/features/experiments/sort-metrics.test.ts
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { sortMetricsForDisplay } from "./sort-metrics";

describe("sortMetricsForDisplay", () => {
  it("puts regressions first", () => {
    const out = sortMetricsForDisplay([
      { status: "improved" },
      { status: "regression" },
      { status: "unchanged" },
    ]);
    assert.equal(out[0].status, "regression");
  });
});
```

- [ ] **Step 3: Implement pages**

- List: name, status, dataset_id, application_version, created_at
- Detail: summary table (mean_score, pass_rate, counts); Evaluate dialog (multi-select evaluators); link Compare; link Release with query `?experiment=`
- Compare page: requires baseline (from experiment.baseline_experiment_id or query `?baseline=`); render `CompareTable`

- [ ] **Step 4: Run sort test**

```bash
cd frontend && node --import tsx --test features/experiments/sort-metrics.test.ts
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): experiments summary and baseline compare"
```

---

### Task 7: Release check UI

**Files:**
- Create: `frontend/lib/api/release.ts`, `frontend/features/release/use-release.ts`, `frontend/features/release/release-check-form.tsx`, `frontend/features/release/release-result.tsx`
- Modify: `frontend/app/release/page.tsx`

**Interfaces:**
- Produces: `postReleaseCheck(projectId, { experiment_id, baseline_experiment_id?, policy })`
- YAML parse via `js-yaml` into policy object; show parse errors inline
- `ReleaseResult`: PASS/FAIL header; checklist rows; HTTP errors ≠ FAIL badge

- [ ] **Step 1: Default policy YAML fixture in form**

```yaml
quality:
  min: 0.85
latency:
  p95_max_ms: 2000
regression:
  max_delta: -0.03
```

- [ ] **Step 2: Implement form + result**

```ts
export function postReleaseCheck(
  projectId: string,
  body: {
    experiment_id: string;
    baseline_experiment_id?: string | null;
    policy: Record<string, unknown>;
  },
) {
  return apiPost<ReleaseCheckResponse>(
    `/api/v1/projects/${projectId}/release-check`,
    body,
  );
}
```

Result UI:

```text
● FAIL
quality.min  passed  actual … threshold …
latency.p95  failed  …
```

Failed rows link to `/experiments/{id}/compare` when baseline present.

- [ ] **Step 3: Policy parse helper test**

```ts
// frontend/features/release/parse-policy.test.ts
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parsePolicyYaml } from "./parse-policy";

describe("parsePolicyYaml", () => {
  it("parses quality.min policy", () => {
    const p = parsePolicyYaml("quality:\n  min: 0.85\n");
    assert.equal((p as { quality: { min: number } }).quality.min, 0.85);
  });
  it("throws on invalid yaml", () => {
    assert.throws(() => parsePolicyYaml(":"));
  });
});
```

- [ ] **Step 4: Pass tests + commit**

```bash
cd frontend && node --import tsx --test features/release/parse-policy.test.ts
git add frontend
git commit -m "feat(frontend): release check PASS/FAIL UI"
```

---

### Task 8: Overview (thin) + Compose web service + Playwright smoke

**Files:**
- Create: `frontend/features/overview/overview-dashboard.tsx`, `frontend/Dockerfile`, `frontend/tests/e2e/smoke.spec.ts`, `frontend/playwright.config.ts`
- Modify: `frontend/app/overview/page.tsx`, `docker-compose.yml`, `docs/07-frontend.md`, root `README.md` (FE quickstart one-liner)

**Interfaces:**
- Overview derives KPIs client-side from recent traces list + latest experiments summary (no new backend endpoints in v0.1)
- Compose `web` service depends on `api`, publishes `:3000`, `API_ORIGIN=http://api:8000`

- [ ] **Step 1: Overview KPI strips**

Compute client-side from `listTraces` + `listExperiments` (no new backend endpoints):

- error rate = errored traces / total in window
- latency p95 from durations when `end_time` present
- quality / cost / regressions: show "—" with link to Experiments / Release when aggregations unavailable
- Optional mini sparkline under Latency and Error rate when ≥5 traces (Recharts, `--chart-*`); omit if sparse — never invent points

Recent traces (10) + latest experiments (5) tables underneath. No icon marketing cards. Include `RefreshControl`. Dual-theme spot-check on KPI strip + tables.

- [ ] **Step 2: Dockerfile**

```dockerfile
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
ARG API_ORIGIN=http://api:8000
ENV API_ORIGIN=$API_ORIGIN
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV API_ORIGIN=http://api:8000
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
```

Enable `output: "standalone"` in `next.config.ts`.

- [ ] **Step 3: Update Compose**

```yaml
  web:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      args:
        API_ORIGIN: http://api:8000
    environment:
      API_ORIGIN: http://api:8000
    ports:
      - "3000:3000"
    depends_on:
      - api
```

- [ ] **Step 4: Playwright smoke**

```ts
// frontend/tests/e2e/smoke.spec.ts
import { test, expect } from "@playwright/test";

const API = process.env.API_ORIGIN ?? "http://localhost:8000";

test("trace list and release page render", async ({ page, request }) => {
  const proj = await request.post(`${API}/api/v1/projects`, {
    data: { name: "E2E", slug: `e2e-${Date.now()}` },
  });
  expect(proj.ok()).toBeTruthy();
  const { id } = await proj.json();

  await page.goto(`/traces?project=${id}`);
  await expect(page.getByRole("heading", { name: "Traces" })).toBeVisible();
  await expect(page.getByText(/No traces yet|trace/i)).toBeVisible();

  await page.goto(`/release?project=${id}`);
  await expect(page.getByRole("heading", { name: "Release" })).toBeVisible();
  await expect(page.getByText(/policy/i)).toBeVisible();
});
```

```bash
cd frontend && npx playwright install chromium
npx playwright test
```

Expected: PASS with API + `npm run dev` (or Compose) running.

- [ ] **Step 5: Link design spec from `docs/07-frontend.md`**

Add at top:

```markdown
Detailed UI design: [`docs/superpowers/specs/2026-10-01-frontend-ui-design.md`](superpowers/specs/2026-10-01-frontend-ui-design.md).
```

- [ ] **Step 6: Commit**

```bash
git add frontend docker-compose.yml docs/07-frontend.md README.md
git commit -m "feat(frontend): overview, Compose web service, Playwright smoke"
```

---

## Self-review checklist (author)

1. **Spec coverage:** Overview, Traces list/detail, Datasets, Experiments+compare, Release, dual-theme tokens, chrome (refresh/relative time/toasts/icons), anti-patterns, Compose, Playwright — each has a task.
2. **Deferred intentionally:** human review, flamegraph, sessions, custom dashboards, ⌘K, density toggle, CORS middleware (rewrites instead).
3. **API alignment:** paths match `backend/src/aiobs/api/routes/*.py` and `schemas.py`.
4. **No placeholders:** tasks include concrete types/paths/commands.
5. **Theme parity:** light and dark verified for chrome, tables, waterfall, release result.

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-10-01-frontend-ui.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in this session with checkpoints  

Which approach?
