import type { TraceScore } from "@/lib/api/types";

export const FEEDBACK_NAME = "user_feedback";

export type Feedback = "up" | "down";

function rowThumb(s: TraceScore): Feedback | null {
  const label = (s.label ?? "").toUpperCase();
  if (label === "FAIL") return "down";
  if (label === "PASS") return "up";
  if (s.value == null) return null;
  return s.value < 0.5 ? "down" : "up";
}

/**
 * End-user thumb for this answer, matching the live verdict: "down" if any
 * user_feedback row failed, else "up" if any passed, else null.
 */
export function feedbackThumb(scores: TraceScore[] | undefined): Feedback | null {
  const thumbs = (scores ?? [])
    .filter((s) => s.name === FEEDBACK_NAME)
    .map(rowThumb);
  if (thumbs.includes("down")) return "down";
  if (thumbs.includes("up")) return "up";
  return null;
}
