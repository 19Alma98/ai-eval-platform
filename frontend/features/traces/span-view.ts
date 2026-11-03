import type { Span } from "@/lib/api/types";
import { spanDocuments, spanPrompt, type RagChunk } from "./rag-view";
import { spanInputOutput } from "./span-metrics";

/**
 * Turns a raw OTel span (flat attribute bag) into what a person wants to read:
 * which model ran, what it was sent, what came back, what failed. The raw
 * attributes stay reachable, grouped by where they come from.
 */

export type ToolCall = { name: string; arguments: string | null };

export type SpanMessage = {
  role: string;
  content: string | null;
  toolCalls: ToolCall[];
};

export type SpanError = {
  type: string | null;
  message: string | null;
  stacktrace: string | null;
};

export type SpanEvent = {
  name: string;
  /** Milliseconds from span start, when the event carries a timestamp. */
  offsetMs: number | null;
  attributes: Record<string, unknown>;
};

export type SpanUsage = {
  prompt: number | null;
  completion: number | null;
  total: number | null;
  cost: number | null;
};

export type SpanView = {
  kind: string;
  durationMs: number | null;
  model: string | null;
  provider: string | null;
  usage: SpanUsage;
  /** Scalar invocation parameters (temperature, max_tokens…). */
  parameters: [string, string][];
  inputMessages: SpanMessage[];
  outputMessages: SpanMessage[];
  documents: RagChunk[] | null;
  input: unknown;
  output: unknown;
  error: SpanError | null;
  events: SpanEvent[];
};

const FLAT_MESSAGE = /^(\d+)\.message\.(.+)$/;
const FLAT_TOOL_CALL = /^tool_calls\.(\d+)\.tool_call\.(.+)$/;
const FLAT_CONTENT = /^contents\.(\d+)\.message_content\.text$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const t = value.trim();
  if (!t || !"{[\"".includes(t[0])) return value;
  try {
    return JSON.parse(t);
  } catch {
    return value;
  }
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function firstNumber(attrs: Record<string, unknown>, ...keys: string[]): number | null {
  for (const key of keys) {
    const n = asNumber(attrs[key]);
    if (n != null) return n;
  }
  return null;
}

function firstString(attrs: Record<string, unknown>, ...keys: string[]): string | null {
  for (const key of keys) {
    const v = attrs[key];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return null;
}

function text(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return value.trim() ? value : null;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** Collect `prefix.N.message.*` keys into one record per message index. */
function flatMessageRows(
  attrs: Record<string, unknown>,
  prefix: string,
): Map<number, Record<string, unknown>> {
  const head = `${prefix}.`;
  const rows = new Map<number, Record<string, unknown>>();
  for (const [key, value] of Object.entries(attrs)) {
    if (!key.startsWith(head)) continue;
    const match = FLAT_MESSAGE.exec(key.slice(head.length));
    if (!match) continue;
    const idx = Number(match[1]);
    const row = rows.get(idx) ?? {};
    row[match[2]] = value;
    rows.set(idx, row);
  }
  return rows;
}

function messageFromFlat(row: Record<string, unknown>): SpanMessage {
  const calls = new Map<number, Partial<ToolCall>>();
  const contents = new Map<number, string>();
  for (const [key, value] of Object.entries(row)) {
    const call = FLAT_TOOL_CALL.exec(key);
    if (call) {
      const entry = calls.get(Number(call[1])) ?? {};
      if (call[2] === "function.name") entry.name = String(value);
      if (call[2] === "function.arguments") entry.arguments = text(value);
      calls.set(Number(call[1]), entry);
      continue;
    }
    const part = FLAT_CONTENT.exec(key);
    if (part && typeof value === "string") contents.set(Number(part[1]), value);
  }
  const joined = [...contents.entries()].sort(([a], [b]) => a - b).map(([, v]) => v);
  return {
    role: String(row.role ?? "user"),
    content: text(row.content) ?? (joined.length ? joined.join("\n\n") : null),
    toolCalls: [...calls.entries()]
      .sort(([a], [b]) => a - b)
      .map(([, c]) => ({ name: c.name ?? "tool", arguments: c.arguments ?? null })),
  };
}

function toolCallsFrom(value: unknown): ToolCall[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((call) => {
    const fn = isRecord(call.function) ? call.function : call;
    return {
      name: String(fn.name ?? "tool"),
      arguments: text(parseJson(fn.arguments ?? fn.input ?? null)),
    };
  });
}

function messageFromRecord(entry: Record<string, unknown>): SpanMessage {
  const inner = isRecord(entry.message) ? entry.message : entry;
  let content: string | null;
  if (Array.isArray(inner.content)) {
    // Anthropic / OpenAI content parts: keep the text ones.
    const parts = inner.content
      .map((p) => (isRecord(p) ? (p.text ?? p.content) : p))
      .filter((p): p is string => typeof p === "string" && p.trim() !== "");
    content = parts.length ? parts.join("\n\n") : text(inner.content);
  } else if (Array.isArray(inner.parts)) {
    // OTel GenAI semconv: {role, parts:[{type:"text", content}]}
    const parts = inner.parts
      .map((p) => (isRecord(p) ? (p.content ?? p.text) : null))
      .filter((p): p is string => typeof p === "string" && p.trim() !== "");
    content = parts.length ? parts.join("\n\n") : null;
  } else {
    content = text(inner.content);
  }
  return {
    role: String(inner.role ?? "user"),
    content,
    toolCalls: toolCallsFrom(inner.tool_calls),
  };
}

function hasBody(m: SpanMessage): boolean {
  return m.content != null || m.toolCalls.length > 0;
}

function messagesFromAttrs(
  attrs: Record<string, unknown>,
  flatPrefix: string,
  jsonKeys: string[],
): SpanMessage[] {
  const flat = flatMessageRows(attrs, flatPrefix);
  if (flat.size) {
    return [...flat.entries()]
      .sort(([a], [b]) => a - b)
      .map(([, row]) => messageFromFlat(row))
      .filter(hasBody);
  }
  for (const key of jsonKeys) {
    const parsed = parseJson(attrs[key]);
    if (Array.isArray(parsed)) {
      const out = parsed.filter(isRecord).map(messageFromRecord).filter(hasBody);
      if (out.length) return out;
    }
  }
  return [];
}

function llmInputMessages(span: Span): SpanMessage[] {
  const attrs = span.attributes ?? {};
  const out = messagesFromAttrs(attrs, "llm.input_messages", [
    "gen_ai.input.messages",
    "llm.input_messages",
  ]);
  if (out.length) return out;
  // Single-string prompts and the `input.value` fallback.
  return spanPrompt(span).map((m) => ({ role: m.role, content: m.content, toolCalls: [] }));
}

function llmOutputMessages(span: Span): SpanMessage[] {
  const attrs = span.attributes ?? {};
  const out = messagesFromAttrs(attrs, "llm.output_messages", [
    "gen_ai.output.messages",
    "llm.output_messages",
  ]);
  if (out.length) return out;
  const completion = firstString(attrs, "gen_ai.completion");
  if (completion) return [{ role: "assistant", content: completion, toolCalls: [] }];
  const response = parseJson(attrs["output.value"]);
  // OpenAI chat completion / Anthropic message bodies.
  if (isRecord(response)) {
    if (Array.isArray(response.choices)) {
      const msgs = response.choices
        .filter(isRecord)
        .map((c) => (isRecord(c.message) ? messageFromRecord(c.message) : null))
        .filter((m): m is SpanMessage => m != null && hasBody(m));
      if (msgs.length) return msgs;
    }
    if (Array.isArray(response.content) && response.role) {
      const m = messageFromRecord(response);
      if (hasBody(m)) return [m];
    }
  }
  const plain = text(decodeValue(attrs["output.value"]));
  return plain ? [{ role: "assistant", content: plain, toolCalls: [] }] : [];
}

/**
 * Make a captured value readable: JSON strings are parsed, and the SDK's
 * `{args, kwargs}` envelope is unwrapped when it holds a single obvious value.
 */
export function decodeValue(raw: unknown): unknown {
  const parsed = parseJson(raw);
  if (isRecord(parsed)) {
    const keys = Object.keys(parsed);
    if (keys.length > 0 && keys.every((k) => k === "args" || k === "kwargs")) {
      const args = (Array.isArray(parsed.args) ? parsed.args : []).filter(
        (v) => !(typeof v === "string" && /^<.+ (object|class) at 0x/.test(v)),
      );
      const kwargs = isRecord(parsed.kwargs) ? parsed.kwargs : {};
      const kwKeys = Object.keys(kwargs);
      if (args.length === 0 && kwKeys.length === 0) return null;
      if (args.length === 0) return kwKeys.length === 1 ? kwargs[kwKeys[0]] : kwargs;
      if (kwKeys.length === 0) return args.length === 1 ? args[0] : args;
      return { args, ...kwargs };
    }
  }
  return parsed;
}

function nanosToMs(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value / 1e6;
  if (typeof value === "string" && /^\d+$/.test(value)) return Number(BigInt(value) / BigInt(1000)) / 1000;
  return null;
}

export function spanEvents(span: Span): SpanEvent[] {
  const start = new Date(span.start_time).getTime();
  return (span.events ?? []).map((ev) => {
    const at = nanosToMs(ev.time_unix_nano);
    return {
      name: typeof ev.name === "string" && ev.name ? ev.name : "event",
      offsetMs: at != null && Number.isFinite(start) ? Math.max(0, at - start) : null,
      attributes: isRecord(ev.attributes) ? ev.attributes : {},
    };
  });
}

export function spanError(span: Span, events: SpanEvent[] = spanEvents(span)): SpanError | null {
  const exc = events.find((e) => e.name === "exception");
  if (exc) {
    return {
      type: firstString(exc.attributes, "exception.type"),
      message: firstString(exc.attributes, "exception.message"),
      stacktrace: firstString(exc.attributes, "exception.stacktrace"),
    };
  }
  if (span.status.toLowerCase() === "error") {
    const attrs = span.attributes ?? {};
    return {
      type: firstString(attrs, "error.type", "exception.type"),
      message: firstString(attrs, "status.message", "otel.status_description", "error.message"),
      stacktrace: null,
    };
  }
  return null;
}

function invocationParameters(attrs: Record<string, unknown>): [string, string][] {
  const out: [string, string][] = [];
  const params = parseJson(attrs["llm.invocation_parameters"]);
  if (isRecord(params)) {
    for (const [k, v] of Object.entries(params)) {
      if (k === "model" || k === "messages" || k === "tools") continue;
      if (v === null || typeof v === "object") continue;
      out.push([k, String(v)]);
    }
  }
  for (const [key, value] of Object.entries(attrs)) {
    const m = /^gen_ai\.request\.(.+)$/.exec(key);
    if (!m || m[1] === "model" || value === null || typeof value === "object") continue;
    if (!out.some(([k]) => k === m[1])) out.push([m[1], String(value)]);
  }
  return out;
}

export function spanDurationMs(span: Span): number | null {
  if (!span.end_time) return null;
  return new Date(span.end_time).getTime() - new Date(span.start_time).getTime();
}

export function buildSpanView(span: Span): SpanView {
  const attrs = span.attributes ?? {};
  const kind = span.kind.toUpperCase();
  const isLlm = kind === "LLM";
  const events = spanEvents(span);
  const io = spanInputOutput(span);
  const prompt = firstNumber(
    attrs,
    "llm.token_count.prompt",
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.prompt_tokens",
  );
  const completion = firstNumber(
    attrs,
    "llm.token_count.completion",
    "gen_ai.usage.output_tokens",
    "gen_ai.usage.completion_tokens",
  );
  const total =
    firstNumber(attrs, "llm.token_count.total", "gen_ai.usage.total_tokens") ??
    (prompt != null || completion != null ? (prompt ?? 0) + (completion ?? 0) : null);

  return {
    kind,
    durationMs: spanDurationMs(span),
    model: firstString(attrs, "llm.model_name", "gen_ai.response.model", "gen_ai.request.model"),
    provider: firstString(attrs, "llm.provider", "llm.system", "gen_ai.system", "gen_ai.provider.name"),
    usage: { prompt, completion, total, cost: firstNumber(attrs, "gen_ai.usage.cost", "llm.cost") },
    parameters: invocationParameters(attrs),
    inputMessages: isLlm ? llmInputMessages(span) : [],
    outputMessages: isLlm ? llmOutputMessages(span) : [],
    documents: kind === "RETRIEVER" || kind === "RERANKER" ? spanDocuments(span) : null,
    input: decodeValue(io.input),
    output: decodeValue(io.output),
    error: spanError(span, events),
    events,
  };
}

export type AttributeGroup = {
  id: string;
  label: string;
  /** Shown collapsed: either already rendered in the overview, or plumbing. */
  collapsed: boolean;
  entries: [string, unknown][];
};

const GROUPS: { id: string; label: string; collapsed: boolean; match: (key: string) => boolean }[] = [
  {
    id: "messages",
    label: "Messages",
    collapsed: true,
    match: (k) =>
      k.startsWith("llm.input_messages") ||
      k.startsWith("llm.output_messages") ||
      k === "gen_ai.input.messages" ||
      k === "gen_ai.output.messages" ||
      k === "gen_ai.prompt" ||
      k === "gen_ai.completion",
  },
  {
    id: "model",
    label: "Model call",
    collapsed: false,
    match: (k) => k.startsWith("llm.") || k.startsWith("gen_ai."),
  },
  { id: "io", label: "Input & output", collapsed: true, match: (k) => /^(input|output)(\.|$)/.test(k) },
  {
    id: "retrieval",
    label: "Retrieval",
    collapsed: true,
    match: (k) => /^(retrieval|reranker|embedding|document)\./.test(k),
  },
  {
    id: "context",
    label: "Trace context",
    collapsed: false,
    match: (k) =>
      k.startsWith("opengrade.") ||
      ["session.id", "user.id", "tag.tags", "metadata", "deployment.environment", "service.version"].includes(k),
  },
  {
    id: "resource",
    label: "SDK & resource",
    collapsed: true,
    match: (k) => /^(service|telemetry|process|host|os|openinference|otel|container|k8s|cloud)\./.test(k),
  },
];

export function groupAttributes(attributes: Record<string, unknown>): AttributeGroup[] {
  const custom: [string, unknown][] = [];
  const buckets = new Map<string, [string, unknown][]>();
  const keys = Object.keys(attributes ?? {}).sort((a, b) =>
    a.localeCompare(b, undefined, { numeric: true }),
  );
  for (const key of keys) {
    const group = GROUPS.find((g) => g.match(key));
    if (!group) {
      custom.push([key, attributes[key]]);
      continue;
    }
    const list = buckets.get(group.id) ?? [];
    list.push([key, attributes[key]]);
    buckets.set(group.id, list);
  }
  const out: AttributeGroup[] = [];
  if (custom.length) out.push({ id: "custom", label: "Custom", collapsed: false, entries: custom });
  for (const g of GROUPS) {
    const entries = buckets.get(g.id);
    if (entries?.length) out.push({ id: g.id, label: g.label, collapsed: g.collapsed, entries });
  }
  // Model call first for LLM spans, custom attributes first otherwise — both
  // are "what this step is about"; keep the order stable otherwise.
  return out.sort((a, b) => rank(a.id) - rank(b.id));
}

function rank(id: string): number {
  return ["model", "custom", "context", "io", "retrieval", "messages", "resource"].indexOf(id);
}
