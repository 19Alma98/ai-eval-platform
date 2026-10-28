/**
 * Human-facing names and one-line explanations for evaluator kinds.
 * The API speaks in snake_case kinds (`answer_relevance`); the UI never should.
 */

export type MetricCategory = "retrieval" | "generation" | "performance" | "other";

export type MetricInfo = {
  label: string;
  description: string;
  category: MetricCategory;
};

export const METRIC_CATEGORY_LABELS: Record<MetricCategory, string> = {
  retrieval: "Retrieval",
  generation: "Answer quality",
  performance: "Performance",
  other: "Other checks",
};

export const METRIC_CATEGORY_ORDER: MetricCategory[] = [
  "generation",
  "retrieval",
  "performance",
  "other",
];

const CATALOG: Record<string, MetricInfo> = {
  correctness: {
    label: "Correctness",
    description: "Does the answer match the facts in the expected answer?",
    category: "generation",
  },
  groundedness: {
    label: "Groundedness",
    description:
      "Is every claim in the answer supported by the retrieved documents? Low scores signal hallucinations.",
    category: "generation",
  },
  answer_relevance: {
    label: "Answer relevance",
    description: "Does the answer actually address the question asked?",
    category: "generation",
  },
  must_contain: {
    label: "Required phrases",
    description: "Does the answer include the phrases the test case requires?",
    category: "generation",
  },
  exact_match: {
    label: "Exact match",
    description: "Is the answer identical to the expected answer?",
    category: "generation",
  },
  contains: {
    label: "Contains",
    description: "Does the answer contain the expected text?",
    category: "generation",
  },
  regex: {
    label: "Pattern match",
    description: "Does the answer match the configured regular expression?",
    category: "other",
  },
  json_schema: {
    label: "Valid JSON",
    description: "Does the output match the expected JSON schema?",
    category: "other",
  },
  tool_call_success: {
    label: "Tool call success",
    description: "Did the expected tool calls succeed?",
    category: "other",
  },
  hit_at_k: {
    label: "Hit rate",
    description: "Was at least one expected document among the top-k retrieved?",
    category: "retrieval",
  },
  recall_at_k: {
    label: "Document recall",
    description: "Share of expected documents found in the top-k retrieved.",
    category: "retrieval",
  },
  mrr: {
    label: "Ranking (MRR)",
    description:
      "How high the first expected document ranks in the results (1 = first position).",
    category: "retrieval",
  },
  context_precision: {
    label: "Context precision",
    description: "Share of retrieved documents that are relevant to the question.",
    category: "retrieval",
  },
  context_recall: {
    label: "Context recall",
    description:
      "Do the retrieved documents contain everything needed for the expected answer?",
    category: "retrieval",
  },
  latency: {
    label: "Latency",
    description: "Did the response arrive within the latency budget?",
    category: "performance",
  },
  token_usage: {
    label: "Token usage",
    description: "Did the call stay within the token budget?",
    category: "performance",
  },
  cost: {
    label: "Cost",
    description: "Did the call stay within the cost budget?",
    category: "performance",
  },
};

/** "answer_relevance" → "Answer relevance"; keeps custom names readable. */
export function humanizeIdentifier(value: string): string {
  const spaced = value.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  if (!spaced) return value;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function metricInfo(nameOrKind: string | null | undefined): MetricInfo {
  const key = (nameOrKind ?? "").trim().toLowerCase();
  const known = CATALOG[key];
  if (known) return known;
  return {
    label: key ? humanizeIdentifier(nameOrKind!.trim()) : "Unnamed metric",
    description: "",
    category: "other",
  };
}

export function metricLabel(nameOrKind: string | null | undefined): string {
  return metricInfo(nameOrKind).label;
}

/**
 * Name to use in code (`evaluate(metrics=["hit_at_k"])`) when it differs from the
 * label, so "Hit rate" can be matched to `hit_at_k`. Null when they read the same.
 */
export function metricCodeName(nameOrKind: string | null | undefined): string | null {
  const raw = (nameOrKind ?? "").trim();
  if (!raw) return null;
  return metricLabel(raw).toLowerCase() === humanizeIdentifier(raw).toLowerCase() ? null : raw;
}

const SDK_SET_NAME = /^sdk:(.+)@([0-9a-f]+)$/i;

/**
 * Sets created by `opengrade.evaluate(metrics=[…])` are named
 * `sdk:hit_at_k+must_contain@689cc45d`; show the metrics instead of the raw key.
 */
export function metricsSetDisplayName(name: string): string {
  const match = SDK_SET_NAME.exec(name.trim());
  if (!match) return name;
  const labels = match[1].split("+").filter(Boolean).map(metricLabel);
  return `From code: ${labels.join(", ")}`;
}

export function compareMetrics(a: string, b: string): number {
  const ia = metricInfo(a);
  const ib = metricInfo(b);
  const ca = METRIC_CATEGORY_ORDER.indexOf(ia.category);
  const cb = METRIC_CATEGORY_ORDER.indexOf(ib.category);
  if (ca !== cb) return ca - cb;
  return ia.label.localeCompare(ib.label);
}

export function groupByMetricCategory<T>(
  rows: T[],
  nameOf: (row: T) => string | null | undefined,
): { category: MetricCategory; label: string; rows: T[] }[] {
  const buckets = new Map<MetricCategory, T[]>();
  for (const row of rows) {
    const category = metricInfo(nameOf(row)).category;
    const bucket = buckets.get(category) ?? [];
    bucket.push(row);
    buckets.set(category, bucket);
  }
  return METRIC_CATEGORY_ORDER.filter((c) => buckets.has(c)).map((category) => ({
    category,
    label: METRIC_CATEGORY_LABELS[category],
    rows: [...buckets.get(category)!].sort((a, b) =>
      compareMetrics(nameOf(a) ?? "", nameOf(b) ?? ""),
    ),
  }));
}
