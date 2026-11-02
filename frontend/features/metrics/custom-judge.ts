import type { Evaluator } from "@/lib/api/types";

/** Backend evaluator kind for project-defined LLM judges. */
export const CUSTOM_JUDGE_KIND = "custom_judge";

export type JudgeScale = "1-5" | "binary";
/** What the judge sees besides the answer (always included). */
export type JudgeField = "input" | "expected" | "documents" | "metadata";

export const JUDGE_FIELD_LABELS: Record<JudgeField, string> = {
  input: "Question",
  expected: "Reference answer",
  documents: "Retrieved documents",
  metadata: "Metadata",
};

export type JudgeDraft = {
  criteria: string;
  scale: JudgeScale;
  fields: JudgeField[];
  live: boolean;
  threshold: string;
  model: string;
};

export const EMPTY_JUDGE_DRAFT: JudgeDraft = {
  criteria: "",
  scale: "1-5",
  fields: ["input"],
  live: false,
  threshold: "0.5",
  model: "",
};

const FIELD_ORDER = ["input", "output", "expected", "documents", "metadata"] as const;

/** Parsed threshold (0..1) or an error message. */
export function parseThreshold(raw: string): number | string {
  const trimmed = raw.trim();
  if (!trimmed) return "Threshold is required";
  const value = Number(trimmed);
  if (!Number.isFinite(value) || value < 0 || value > 1) {
    return "Threshold must be a number between 0 and 1";
  }
  return value;
}

/** First problem with the draft, or null when it can be saved. */
export function judgeDraftError(name: string, draft: JudgeDraft): string | null {
  if (!name.trim()) return "Give the judge a name";
  if (!draft.criteria.trim()) return "Describe what the judge should check";
  if (draft.live && draft.fields.includes("expected")) {
    return "A live judge cannot read the reference answer (production has none)";
  }
  const threshold = parseThreshold(draft.threshold);
  if (typeof threshold === "string") return threshold;
  return null;
}

/** Evaluator config sent to the API (same shape as the SDK's `LlmJudge.config()`). */
export function buildJudgeConfig(draft: JudgeDraft): Record<string, unknown> {
  const selected = new Set<string>([...draft.fields, "output"]);
  const config: Record<string, unknown> = {
    kind: CUSTOM_JUDGE_KIND,
    criteria: draft.criteria.trim(),
    scale: draft.scale,
    fields: FIELD_ORDER.filter((f) => selected.has(f)),
  };
  if (draft.live) {
    config.live = true;
    const threshold = parseThreshold(draft.threshold);
    if (typeof threshold === "number") config.threshold = threshold;
  }
  if (draft.model.trim()) config.model = draft.model.trim();
  return config;
}

export function isCustomJudge(evaluator: Evaluator): boolean {
  return evaluator.config?.kind === CUSTOM_JUDGE_KIND;
}

/** Latest version of each custom judge, sorted by name. */
export function latestCustomJudges(evaluators: Evaluator[]): Evaluator[] {
  const latest = new Map<string, Evaluator>();
  for (const e of evaluators) {
    if (!isCustomJudge(e)) continue;
    const current = latest.get(e.name);
    if (!current || e.version > current.version) latest.set(e.name, e);
  }
  return [...latest.values()].sort((a, b) => a.name.localeCompare(b.name));
}

/** Version for a new judge called `name` (a changed config is a new version). */
export function nextJudgeVersion(evaluators: Evaluator[], name: string): number {
  const versions = evaluators.filter((e) => e.name === name.trim()).map((e) => e.version);
  return versions.length ? Math.max(...versions) + 1 : 1;
}

/** Latest custom judges that no entry of a metrics set uses yet (by name or evaluator). */
export function judgesNotInSet(
  evaluators: Evaluator[],
  entries: { kind: string; evaluator_id: string | null }[],
): Evaluator[] {
  const kinds = new Set(entries.map((e) => e.kind));
  const ids = new Set(entries.map((e) => e.evaluator_id));
  return latestCustomJudges(evaluators).filter((e) => !kinds.has(e.name) && !ids.has(e.id));
}
