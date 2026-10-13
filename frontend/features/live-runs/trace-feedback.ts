import type { TraceScore } from "@/lib/api/types";

export const FEEDBACK_NAME = "user_feedback";

export type Feedback = "up" | "down";

/** Most recent end-user thumbs on this answer, if any. */
export function latestFeedback(scores: TraceScore[] | undefined): Feedback | null {
  const feedback = (scores ?? []).filter((s) => s.name === FEEDBACK_NAME && s.value != null);
  if (feedback.length === 0) return null;
  const latest = feedback.reduce((a, b) => (b.updated_at > a.updated_at ? b : a));
  return (latest.value ?? 0) >= 0.5 ? "up" : "down";
}
