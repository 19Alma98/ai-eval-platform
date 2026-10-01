import type { Span } from "@/lib/api/types";

function attrNumber(
  attrs: Record<string, unknown>,
  ...keys: string[]
): number | null {
  for (const key of keys) {
    const v = attrs[key];
    if (typeof v === "number" && Number.isFinite(v)) return v;
    if (typeof v === "string" && v.trim() !== "") {
      const n = Number(v);
      if (Number.isFinite(n)) return n;
    }
  }
  return null;
}

export function spanTokenSummary(span: Span): {
  total: string;
  prompt: string;
  completion: string;
} {
  const attrs = span.attributes ?? {};
  const total = attrNumber(
    attrs,
    "gen_ai.usage.total_tokens",
    "llm.token_count.total",
  );
  const prompt = attrNumber(
    attrs,
    "gen_ai.usage.input_tokens",
    "llm.token_count.prompt",
    "gen_ai.usage.prompt_tokens",
  );
  const completion = attrNumber(
    attrs,
    "gen_ai.usage.output_tokens",
    "llm.token_count.completion",
    "gen_ai.usage.completion_tokens",
  );
  return {
    total: total != null ? String(total) : "—",
    prompt: prompt != null ? String(prompt) : "—",
    completion: completion != null ? String(completion) : "—",
  };
}

export function spanCost(span: Span): string {
  const attrs = span.attributes ?? {};
  const cost = attrNumber(attrs, "gen_ai.usage.cost", "llm.cost");
  return cost != null ? `$${cost}` : "—";
}

const IO_KEYS = [
  "input",
  "output",
  "gen_ai.prompt",
  "gen_ai.completion",
  "gen_ai.input.messages",
  "gen_ai.output.messages",
  "llm.input_messages",
  "llm.output_messages",
] as const;

export function spanInputOutput(span: Span): {
  input: unknown;
  output: unknown;
} {
  const attrs = span.attributes ?? {};
  let input: unknown;
  let output: unknown;
  for (const key of IO_KEYS) {
    if (key.includes("input") || key === "gen_ai.prompt") {
      if (input === undefined && attrs[key] !== undefined) input = attrs[key];
    }
    if (key.includes("output") || key === "gen_ai.completion") {
      if (output === undefined && attrs[key] !== undefined) output = attrs[key];
    }
  }
  if (input === undefined && attrs.input !== undefined) input = attrs.input;
  if (output === undefined && attrs.output !== undefined) output = attrs.output;
  return { input, output };
}

export function isRedactedValue(value: unknown): boolean {
  if (typeof value === "string") {
    return /\[REDACTED\]|redacted/i.test(value);
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const meta = (value as Record<string, unknown>).redacted;
    return meta === true;
  }
  return false;
}
