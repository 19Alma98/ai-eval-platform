import type { TraceSummary } from "@/lib/api/types";

const EVAL_TRACE_PREFIX = "opengrade.eval ";

/** Lead with what the user asked; the span name is context, not the headline. */
export function traceLabel(row: Pick<TraceSummary, "name" | "input_preview">): {
  title: string;
  subtitle: string | null;
} {
  const source = row.name.startsWith(EVAL_TRACE_PREFIX)
    ? `Experiment · ${row.name.slice(EVAL_TRACE_PREFIX.length)}`
    : row.name;
  const question = row.input_preview?.trim();
  return question ? { title: question, subtitle: source } : { title: source, subtitle: null };
}
