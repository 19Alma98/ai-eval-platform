import type { LiveInteraction } from "@/lib/api/types";

export type JudgeClaim = {
  text: string;
  verdict: string;
  docIds: string[];
  quote: string | null;
  reasoning: string | null;
};

export type VerdictTone = "ok" | "warn" | "fail";

export const JUDGE_MODEL_UNSUITABLE = "judge_model_unsuitable";
export const LIVE_UNSUITABLE_RATE = 0.2;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

export function parseJudgeClaims(
  metadata: Record<string, unknown> | undefined,
  key: "claims" | "answer_claims" = "claims",
): JudgeClaim[] | null {
  const raw = metadata?.[key];
  if (!Array.isArray(raw)) return null;
  const claims: JudgeClaim[] = [];
  for (const entry of raw) {
    if (!isRecord(entry)) continue;
    if (typeof entry.text !== "string" || typeof entry.verdict !== "string") continue;
    claims.push({
      text: entry.text,
      verdict: entry.verdict,
      docIds: Array.isArray(entry.doc_ids)
        ? entry.doc_ids.filter((id): id is string => typeof id === "string")
        : [],
      quote: optionalString(entry.quote),
      reasoning: optionalString(entry.reasoning),
    });
  }
  return claims;
}

export function verdictTone(verdict: string): VerdictTone {
  if (verdict === "supported" || verdict === "covered") return "ok";
  if (verdict === "contradicted") return "fail";
  return "warn";
}

export function runJudgeWarning(
  metadata: Record<string, unknown> | undefined,
): string | null {
  const warnings = metadata?.warnings;
  if (!Array.isArray(warnings) || !warnings.includes(JUDGE_MODEL_UNSUITABLE)) {
    return null;
  }
  const detail = metadata?.warning_detail;
  return (isRecord(detail) && optionalString(detail.message)) || "Judge model unsuitable";
}

export function liveUnsuitableRate(rows: LiveInteraction[]): number {
  let total = 0;
  let invalid = 0;
  for (const row of rows) {
    for (const score of row.scores) {
      if (typeof score.metadata?.judge_kind !== "string") continue;
      if ((score.label ?? "").trim().toUpperCase() === "SKIPPED") continue;
      total += 1;
      if (score.metadata?.error_type === "judge_output_invalid") invalid += 1;
    }
  }
  return total === 0 ? 0 : invalid / total;
}
