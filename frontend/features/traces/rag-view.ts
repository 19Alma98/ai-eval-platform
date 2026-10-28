import type { JudgeClaim } from "@/features/judges/judge-metadata";
import type { Span, TraceDetail } from "@/lib/api/types";
import { spanInputOutput } from "./span-metrics";

export type RagChunk = {
  id: string;
  title: string | null;
  text: string | null;
  score: number | null;
};

export type RagStage = {
  spanId: string;
  name: string;
  kind: string;
  chunks: RagChunk[];
};

export type RagMessage = { role: string; content: string };

export type RagView = {
  query: string | null;
  stages: RagStage[];
  prompt: RagMessage[];
  promptSpanId: string | null;
  answer: string | null;
};

const RETRIEVAL_KINDS = new Set(["RETRIEVER", "RERANKER"]);
const DOCUMENT_KEYS: Record<string, string[]> = {
  RETRIEVER: ["retrieval.documents", "documents"],
  RERANKER: ["reranker.output_documents", "retrieval.documents", "documents"],
};
const QUESTION_KEYS = ["question", "query", "input", "prompt", "message", "text"];
const ANSWER_KEYS = ["answer", "output", "response", "content", "text"];
const FLAT_DOCUMENT = /^(\d+)\.document\.(.+)$/;
const FLAT_MESSAGE = /^(\d+)\.message\.(role|content)$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
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

function nonEmpty(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function asText(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return nonEmpty(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function pickKey(record: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const v = nonEmpty(record[key]);
    if (v) return v;
  }
  return null;
}

/** Mirrors the backend's question extraction from `@opengrade.trace` input. */
export function questionFromInput(raw: unknown): string | null {
  const parsed = parseJson(raw);
  if (typeof parsed === "string") return nonEmpty(parsed);
  if (isRecord(parsed)) {
    const keys = Object.keys(parsed);
    if (keys.every((k) => k === "args" || k === "kwargs")) {
      const args = Array.isArray(parsed.args) ? parsed.args : [];
      const kwargs = isRecord(parsed.kwargs) ? parsed.kwargs : {};
      const picked = pickKey(kwargs, QUESTION_KEYS);
      if (picked) return picked;
      const strings = [...args, ...Object.values(kwargs)].filter(
        (v): v is string =>
          typeof v === "string" && v.trim() !== "" && !/^<.+ (object|class) at 0x/.test(v),
      );
      if (strings.length === 1) return strings[0];
      return null;
    }
    const picked = pickKey(parsed, QUESTION_KEYS);
    if (picked) return picked;
  }
  return asText(raw);
}

export function answerFromOutput(raw: unknown): string | null {
  const parsed = parseJson(raw);
  if (typeof parsed === "string") return nonEmpty(parsed);
  if (isRecord(parsed)) {
    const picked = pickKey(parsed, ANSWER_KEYS);
    if (picked) return picked;
  }
  return asText(raw);
}

function toChunk(doc: Record<string, unknown>): RagChunk | null {
  const parsedMetadata = parseJson(doc.metadata);
  const metadata = isRecord(parsedMetadata) ? parsedMetadata : {};
  const rawId = doc.id ?? metadata.doc_id ?? metadata.document_id ?? metadata.node_id ?? metadata.id;
  if (rawId === null || rawId === undefined || String(rawId).trim() === "") return null;
  return {
    id: String(rawId).trim(),
    title: nonEmpty(doc.title) ?? nonEmpty(metadata.title) ?? nonEmpty(metadata.file_name),
    text: nonEmpty(doc.text) ?? nonEmpty(doc.content) ?? nonEmpty(doc.page_content),
    score: asNumber(doc.score ?? metadata.score),
  };
}

function flattenedDocuments(
  attrs: Record<string, unknown>,
  prefix: string,
): RagChunk[] | null {
  const head = `${prefix}.`;
  const rows = new Map<number, Record<string, unknown>>();
  for (const [key, value] of Object.entries(attrs)) {
    if (!key.startsWith(head)) continue;
    const match = FLAT_DOCUMENT.exec(key.slice(head.length));
    if (!match) continue;
    const idx = Number(match[1]);
    const row = rows.get(idx) ?? {};
    row[match[2]] = value;
    rows.set(idx, row);
  }
  if (rows.size === 0) return null;
  return [...rows.entries()]
    .sort(([a], [b]) => a - b)
    .map(([, row]) => toChunk(row))
    .filter((c): c is RagChunk => c !== null);
}

export function spanDocuments(span: Span): RagChunk[] | null {
  const attrs = span.attributes ?? {};
  for (const key of DOCUMENT_KEYS[span.kind.toUpperCase()] ?? []) {
    const raw = parseJson(attrs[key]);
    if (raw === undefined || raw === null) {
      const flat = flattenedDocuments(attrs, key);
      if (flat) return flat;
      continue;
    }
    if (!Array.isArray(raw)) return [];
    return raw
      .filter(isRecord)
      .map(toChunk)
      .filter((c): c is RagChunk => c !== null);
  }
  return null;
}

function messagesFrom(value: unknown): RagMessage[] {
  const parsed = parseJson(value);
  if (!Array.isArray(parsed)) return [];
  const out: RagMessage[] = [];
  for (const entry of parsed) {
    if (!isRecord(entry)) continue;
    const inner = isRecord(entry.message) ? entry.message : entry;
    const content = asText(inner.content);
    if (content) out.push({ role: String(inner.role ?? "user"), content });
  }
  return out;
}

function flattenedMessages(attrs: Record<string, unknown>, prefix: string): RagMessage[] {
  const head = `${prefix}.`;
  const rows = new Map<number, Partial<RagMessage>>();
  for (const [key, value] of Object.entries(attrs)) {
    if (!key.startsWith(head)) continue;
    const match = FLAT_MESSAGE.exec(key.slice(head.length));
    if (!match) continue;
    const idx = Number(match[1]);
    const row = rows.get(idx) ?? {};
    row[match[2] as "role" | "content"] = String(value);
    rows.set(idx, row);
  }
  return [...rows.entries()]
    .sort(([a], [b]) => a - b)
    .filter(([, row]) => row.content)
    .map(([, row]) => ({ role: row.role ?? "user", content: row.content! }));
}

export function spanPrompt(span: Span): RagMessage[] {
  const attrs = span.attributes ?? {};
  const flat = flattenedMessages(attrs, "llm.input_messages");
  if (flat.length) return flat;
  for (const key of ["gen_ai.input.messages", "llm.input_messages", "gen_ai.prompt"]) {
    const messages = messagesFrom(attrs[key]);
    if (messages.length) return messages;
    const text = typeof attrs[key] === "string" ? nonEmpty(attrs[key]) : null;
    if (text) return [{ role: "user", content: text }];
  }
  const input = attrs["input.value"] ?? spanInputOutput(span).input;
  const fallback = asText(parseJson(input));
  return fallback ? [{ role: "user", content: fallback }] : [];
}

function spanAnswer(span: Span): string | null {
  const attrs = span.attributes ?? {};
  const flat = flattenedMessages(attrs, "llm.output_messages");
  if (flat.length) return flat[flat.length - 1].content;
  const messages = messagesFrom(attrs["gen_ai.output.messages"]);
  if (messages.length) return messages[messages.length - 1].content;
  return answerFromOutput(attrs["output.value"] ?? spanInputOutput(span).output);
}

const byStart = (a: Span, b: Span) =>
  new Date(a.start_time).getTime() - new Date(b.start_time).getTime();

export function buildRagView(trace: TraceDetail): RagView {
  const spans = [...trace.spans].sort(byStart);
  const stages: RagStage[] = [];
  for (const span of spans) {
    if (!RETRIEVAL_KINDS.has(span.kind.toUpperCase())) continue;
    const chunks = spanDocuments(span);
    if (chunks === null) continue;
    stages.push({ spanId: span.span_id, name: span.name, kind: span.kind.toUpperCase(), chunks });
  }

  const llmSpans = spans.filter((s) => s.kind.toUpperCase() === "LLM");
  const promptSpan = llmSpans[llmSpans.length - 1] ?? null;
  const retrieverInput = spans.find((s) => RETRIEVAL_KINDS.has(s.kind.toUpperCase()));

  const query =
    questionFromInput(trace.input) ??
    (retrieverInput
      ? questionFromInput(
          retrieverInput.attributes["input.value"] ?? spanInputOutput(retrieverInput).input,
        )
      : null);
  const answer =
    answerFromOutput(trace.output) ?? (promptSpan ? spanAnswer(promptSpan) : null);

  return {
    query,
    stages,
    prompt: promptSpan ? spanPrompt(promptSpan) : [],
    promptSpanId: promptSpan?.span_id ?? null,
    answer,
  };
}

export function hasRagContent(view: RagView): boolean {
  return view.stages.length > 0 || view.prompt.length > 0;
}

export type HighlightPart = { text: string; claimIndexes: number[] };

/**
 * Split a chunk's text into parts, tagging the ranges quoted by judge claims.
 * Quotes are matched case-insensitively; overlapping quotes share a part.
 */
export function highlightQuotes(
  text: string,
  claims: Pick<JudgeClaim, "quote">[],
): HighlightPart[] {
  const lower = text.toLowerCase();
  const marks: { start: number; end: number; claim: number }[] = [];
  claims.forEach((claim, i) => {
    const quote = claim.quote?.trim();
    if (!quote) return;
    const at = lower.indexOf(quote.toLowerCase());
    if (at >= 0) marks.push({ start: at, end: at + quote.length, claim: i });
  });
  if (marks.length === 0) return [{ text, claimIndexes: [] }];
  const cuts = new Set<number>([0, text.length]);
  for (const m of marks) {
    cuts.add(m.start);
    cuts.add(m.end);
  }
  const points = [...cuts].sort((a, b) => a - b);
  const parts: HighlightPart[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const [from, to] = [points[i], points[i + 1]];
    if (from === to) continue;
    parts.push({
      text: text.slice(from, to),
      claimIndexes: marks.filter((m) => m.start <= from && m.end >= to).map((m) => m.claim),
    });
  }
  return parts;
}

export function claimsForChunk(chunk: RagChunk, claims: JudgeClaim[]): number[] {
  const lower = chunk.text?.toLowerCase() ?? "";
  const out: number[] = [];
  claims.forEach((claim, i) => {
    const quote = claim.quote?.trim().toLowerCase();
    if (claim.docIds.includes(chunk.id) || (quote && lower.includes(quote))) out.push(i);
  });
  return out;
}
