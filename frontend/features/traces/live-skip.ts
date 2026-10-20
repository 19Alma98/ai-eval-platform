import type { Span, TraceDetail } from "@/lib/api/types";

function truthy(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  return ["1", "true", "yes", "on"].includes(String(value).trim().toLowerCase());
}

export type LiveSkipReason = "no_content" | "empty";

/**
 * Why a live-marked trace has no live interaction, or null when it is not skipped.
 * Ingestion skips it when the live span carries no `input.value` / `output.value`
 * (server `CONTENT_CAPTURE_ENABLED=false`, the default, or SDK capture off), or when
 * the question or answer reads as empty. Experiment traces are never live.
 */
export function liveSkipReason(
  trace: Pick<TraceDetail, "spans" | "live_interaction_id">,
): LiveSkipReason | null {
  if (trace.live_interaction_id) return null;
  if (trace.spans.some((s) => s.attributes?.["opengrade.experiment_id"] != null)) return null;
  const live: Span | undefined = trace.spans.find((s) => truthy(s.attributes?.["opengrade.live"]));
  if (!live) return null;
  const attrs = live.attributes ?? {};
  return "input.value" in attrs || "output.value" in attrs ? "empty" : "no_content";
}
