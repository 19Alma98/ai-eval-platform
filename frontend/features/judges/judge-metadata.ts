export type JudgeClaim = {
  text: string;
  verdict: string;
  docIds: string[];
  quote: string | null;
  reasoning: string | null;
};

export type VerdictTone = "ok" | "warn" | "fail";

export const JUDGE_MODEL_UNSUITABLE = "judge_model_unsuitable";

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

export function liveJudgeWarningMessage(
  warnings: { warning_detail?: Record<string, unknown> }[] | undefined,
): string | null {
  if (!warnings?.length) return null;
  const messages = warnings
    .map((w) => (isRecord(w.warning_detail) ? optionalString(w.warning_detail.message) : null))
    .filter((m): m is string => Boolean(m));
  if (messages.length > 0) return messages.join(" ");
  return "Judge model unsuitable";
}
