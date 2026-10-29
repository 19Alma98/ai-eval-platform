import type { PurgeReport } from "@/lib/api/types";

/** "12 traces, 3 live answers" — what a purge removes. */
export function describePending(report: PurgeReport): string {
  const parts = [
    [report.traces, "trace"],
    [report.live_interactions, "live answer"],
    [report.trace_scores, "score"],
    [report.alert_events, "alert event"],
  ]
    .filter(([n]) => (n as number) > 0)
    .map(([n, label]) => `${(n as number).toLocaleString()} ${label}${n === 1 ? "" : "s"}`);
  return parts.length ? parts.join(", ") : "nothing";
}
