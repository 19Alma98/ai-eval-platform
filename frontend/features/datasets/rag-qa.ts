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
