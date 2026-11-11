export const RAG_QA_TASK = "rag_qa";
export const RAG_CHAT_TASK = "rag_chat";

export const IMPORTABLE_RAG_TASKS = new Set([RAG_QA_TASK, RAG_CHAT_TASK]);

export const RAG_FIELD_HINTS = [
  "input: user question",
  "expected_output: reference answer",
  "metadata.expected_doc_ids: gold document ids (list or pipe-separated)",
  "metadata.must_contain: required answer phrases (optional, list or pipe-separated)",
  "context.documents / retrieval snippets",
  "actual_output: model answer",
] as const;

export const RAG_CHAT_FIELD_HINTS = [
  "input.history: prior {role, content} turns",
  "input.question: final user question",
  "expected_output: reference answer for the last turn",
  "metadata.expected_doc_ids: gold document ids for the last turn",
  "metadata.must_contain: required answer phrases (optional)",
  "context.documents / retrieval snippets for the last turn",
  "context.search_query: rewritten standalone retrieval query (optional)",
  "actual_output: model answer for the last turn",
] as const;

export const RAG_RECOMMENDED_EVALUATOR_KINDS = [
  "hit_at_k",
  "recall_at_k",
  "mrr",
  "context_precision",
  "context_recall",
  "must_contain",
  "groundedness",
  "answer_relevance",
  "correctness",
  "citation_accuracy",
  "refusal",
  "pii",
  "toxicity",
  "prompt_injection",
  "latency",
] as const;

export type ChatTurn = { role: string; content: string };

export function isChatInput(input: unknown): boolean {
  if (!input || typeof input !== "object") return false;
  const question = (input as { question?: unknown }).question;
  return typeof question === "string";
}

export function chatQuestionPreview(input: unknown): string {
  if (typeof input === "string") return input;
  if (input && typeof input === "object" && "question" in input) {
    const question = (input as { question?: unknown }).question;
    if (typeof question === "string" && question.trim()) return question;
  }
  try {
    return JSON.stringify(input);
  } catch {
    return String(input);
  }
}

export function chatHistoryLength(input: unknown): number {
  if (!input || typeof input !== "object") return 0;
  const history = (input as { history?: unknown }).history;
  return Array.isArray(history) ? history.length : 0;
}

/** Table/search preview: optional ``[N prior]`` prefix + last user question. */
export function formatChatQuestion(input: unknown): string {
  const question = chatQuestionPreview(input);
  const prior = chatHistoryLength(input);
  return prior > 0 ? `[${prior} prior] ${question}` : question;
}

/** History turns plus the final user question, for experiment/case detail. */
export function chatTurns(input: unknown): ChatTurn[] {
  if (!input || typeof input !== "object") return [];
  const raw = (input as { history?: unknown }).history;
  const turns: ChatTurn[] = [];
  if (Array.isArray(raw)) {
    for (const entry of raw) {
      if (!entry || typeof entry !== "object") continue;
      const role = (entry as { role?: unknown }).role;
      const content = (entry as { content?: unknown }).content;
      if (typeof role !== "string" || typeof content !== "string") continue;
      turns.push({ role, content });
    }
  }
  const question = (input as { question?: unknown }).question;
  if (typeof question === "string" && question.trim()) {
    turns.push({ role: "user", content: question });
  }
  return turns;
}
