import type { EvaluatorSummary } from "@/lib/api/types";

export type TargetState = "met" | "missed" | "unknown";

/** Whether a metric's run reached its pass threshold, from the summary status. */
export function targetState(status: string | null | undefined): TargetState {
  const key = (status ?? "").toLowerCase();
  if (key === "passed" || key === "pass" || key === "completed" || key === "ok") return "met";
  if (key === "failed" || key === "fail") return "missed";
  return "unknown";
}

export type TargetTally = { met: number; missed: number; total: number };

/** How many of an experiment's metrics meet their target (unknown ones count in total only). */
export function tallyTargets(evaluators: EvaluatorSummary[]): TargetTally {
  let met = 0;
  let missed = 0;
  for (const row of evaluators) {
    const state = targetState(row.status);
    if (state === "met") met += 1;
    else if (state === "missed") missed += 1;
  }
  return { met, missed, total: evaluators.length };
}
