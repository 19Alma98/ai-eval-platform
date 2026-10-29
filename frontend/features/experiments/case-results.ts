import type {
  DatasetItem,
  EvaluationRun,
  EvaluatorSummary,
  ExperimentItemOutput,
} from "@/lib/api/types";
import { compareMetrics, metricInfo } from "@/lib/metrics-catalog";
import { collapseResultsByItem } from "./repeats";
import { buildRunItemViews, type RunItemView } from "./run-items";

export type Outcome = "pass" | "fail" | "skipped" | "error" | "scored" | "pending";

export type MetricRef = {
  evaluatorId: string;
  runId: string;
  name: string;
  label: string;
  description: string;
};

export type CaseMetricResult = {
  metric: MetricRef;
  outcome: Outcome;
  score: number | null;
  explanation: string | null;
  metadata: Record<string, unknown>;
};

export type CaseView = RunItemView & {
  results: CaseMetricResult[];
  failed: CaseMetricResult[];
  nPassed: number;
  nScored: number;
};

export type RetrievedDocument = {
  id: string | null;
  title: string | null;
  text: string;
};

export function outcomeOf(label: string | null | undefined, score: number | null): Outcome {
  const key = (label ?? "").trim().toLowerCase();
  if (key === "pass" || key === "passed") return "pass";
  if (key === "fail" || key === "failed") return "fail";
  if (key === "skipped" || key === "skip") return "skipped";
  if (key === "error") return "error";
  return score === null ? "pending" : "scored";
}

export function metricRefFromSummary(row: EvaluatorSummary): MetricRef {
  const name = row.evaluator_name?.trim() || "";
  const info = metricInfo(name);
  return {
    evaluatorId: row.evaluator_id,
    runId: row.run_id,
    name,
    label: info.label,
    description: info.description,
  };
}

/**
 * One row per test case with every metric's verdict attached, so the UI can show
 * "8/10 passed — failing: Groundedness, Correctness" instead of one metric at a time.
 */
export function buildCaseViews(
  items: DatasetItem[],
  outputs: ExperimentItemOutput[],
  evaluators: EvaluatorSummary[],
  runsById: Map<string, EvaluationRun>,
): CaseView[] {
  const base = buildRunItemViews(items, outputs, []);
  const metrics = evaluators
    .map(metricRefFromSummary)
    .sort((a, b) => compareMetrics(a.name, b.name));

  const resultIndex = new Map<string, Map<string, EvaluationRun["results"][number]>>();
  for (const metric of metrics) {
    const run = runsById.get(metric.runId);
    if (!run) continue;
    resultIndex.set(
      metric.runId,
      collapseResultsByItem(run.results),
    );
  }

  return base.map((view) => {
    const results: CaseMetricResult[] = metrics.map((metric) => {
      const byItem = resultIndex.get(metric.runId);
      const result = byItem?.get(view.datasetItemId);
      if (!result) {
        return {
          metric,
          outcome: byItem ? "skipped" : "pending",
          score: null,
          explanation: null,
          metadata: {},
        };
      }
      return {
        metric,
        outcome: outcomeOf(result.label, result.score),
        score: result.score,
        explanation: result.explanation,
        metadata: result.metadata ?? {},
      };
    });
    const failed = results.filter((r) => r.outcome === "fail" || r.outcome === "error");
    const decided = results.filter((r) => r.outcome === "pass" || r.outcome === "fail");
    return {
      ...view,
      results,
      failed,
      nPassed: decided.filter((r) => r.outcome === "pass").length,
      nScored: decided.length,
    };
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Normalize the retrieval payload into cards; tolerate strings and partial objects. */
export function parseRetrievedDocuments(raw: unknown): RetrievedDocument[] | null {
  if (raw === null || raw === undefined) return null;
  if (!Array.isArray(raw)) return null;
  return raw.map((doc) => {
    if (typeof doc === "string") return { id: null, title: null, text: doc };
    if (!isRecord(doc)) return { id: null, title: null, text: String(doc) };
    const id = doc.id ?? doc.doc_id;
    const text = doc.text ?? doc.content ?? doc.body ?? "";
    return {
      id: typeof id === "string" || typeof id === "number" ? String(id) : null,
      title: typeof doc.title === "string" && doc.title.trim() ? doc.title : null,
      text: typeof text === "string" ? text : JSON.stringify(text),
    };
  });
}

/** Known numeric facts from the run context (latency, tokens) shown as plain stats. */
export function contextStats(context: unknown): { label: string; value: string }[] {
  if (!isRecord(context)) return [];
  const stats: { label: string; value: string }[] = [];
  const latency = context.latency_ms;
  if (typeof latency === "number") {
    stats.push({
      label: "Response time",
      value: latency < 1000 ? `${Math.round(latency)} ms` : `${(latency / 1000).toFixed(2)} s`,
    });
  }
  for (const [key, label] of [
    ["total_tokens", "Tokens"],
    ["prompt_tokens", "Prompt tokens"],
    ["completion_tokens", "Answer tokens"],
  ] as const) {
    const value = context[key];
    if (typeof value === "number") stats.push({ label, value: value.toLocaleString() });
  }
  const cost = context.cost_usd ?? context.cost;
  if (typeof cost === "number") stats.push({ label: "Cost", value: `$${cost.toFixed(4)}` });
  return stats;
}
