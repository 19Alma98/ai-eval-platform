import type { TraceDetail } from "@/lib/api/types";

function truthy(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  return ["1", "true", "yes", "on"].includes(String(value).trim().toLowerCase());
}

/**
 * Marked `opengrade.live` but no live interaction was created: ingestion skips live
 * traces whose question/answer can't be read (content not captured, several string
 * arguments, empty return). Experiment traces are never live, so they don't count.
 */
export function liveTraceSkipped(trace: Pick<TraceDetail, "spans" | "live_interaction_id">): boolean {
  if (trace.live_interaction_id) return false;
  const live = trace.spans.some((s) => truthy(s.attributes?.["opengrade.live"]));
  const experiment = trace.spans.some((s) => s.attributes?.["opengrade.experiment_id"] != null);
  return live && !experiment;
}
