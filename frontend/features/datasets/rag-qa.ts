export const RAG_QA_TASK = "rag_qa";

export const RAG_FIELD_HINTS = [
  "input: user question",
  "expected_output: reference answer",
  "metadata.expected_doc_ids: gold document ids (list or pipe-separated)",
  "metadata.must_contain: required answer phrases (optional, list or pipe-separated)",
  "context.documents / retrieval snippets",
  "actual_output: model answer",
] as const;

export const RAG_RECOMMENDED_EVALUATOR_KINDS = [
  "hit_at_k",
  "recall_at_k",
  "mrr",
  "context_precision",
  "must_contain",
  "groundedness",
  "answer_relevance",
  "correctness",
  "latency",
] as const;
