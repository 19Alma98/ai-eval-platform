import type { LiveInteraction } from "@/lib/api/types";

export type LiveVerdict = "passing" | "failing" | "waiting" | "error" | "not_scored";

export const LIVE_VERDICT_LABELS: Record<LiveVerdict, string> = {
  passing: "Passing",
  failing: "Failing",
  waiting: "Waiting for judge",
  error: "Judge error",
  not_scored: "Not scored",
};

/** One overall verdict per live answer, derived from its judge scores. */
export function liveVerdict(row: Pick<LiveInteraction, "judge_status" | "scores">): LiveVerdict {
  const status = row.judge_status.toLowerCase();
  if (status === "pending" || status === "running") return "waiting";
  if (status === "error") return "error";
  const labels = row.scores.map((s) => (s.label ?? "").toUpperCase());
  if (labels.some((l) => l === "FAIL" || l === "ERROR")) return "failing";
  if (labels.some((l) => l === "PASS")) return "passing";
  return "not_scored";
}
