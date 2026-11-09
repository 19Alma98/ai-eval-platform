/** Starting points offered by the create-evaluator dialog. */
export const EVALUATOR_PRESETS = [
  {
    label: "Exact match",
    type: "deterministic",
    config: { kind: "exact_match" },
  },
  {
    label: "Contains",
    type: "deterministic",
    config: { kind: "contains" },
  },
  {
    label: "Correctness (LLM)",
    type: "llm_judge",
    config: { kind: "correctness" },
  },
  {
    label: "Groundedness (LLM)",
    type: "llm_judge",
    config: { kind: "groundedness" },
  },
  {
    label: "Answer relevance (LLM)",
    type: "llm_judge",
    config: { kind: "answer_relevance" },
  },
  {
    label: "Citation accuracy (LLM)",
    type: "llm_judge",
    config: { kind: "citation_accuracy" },
  },
  {
    label: "Correct refusal (LLM)",
    type: "llm_judge",
    config: { kind: "refusal" },
  },
  {
    label: "PII leak (LLM)",
    type: "llm_judge",
    config: { kind: "pii" },
  },
  {
    label: "Toxicity (LLM)",
    type: "llm_judge",
    config: { kind: "toxicity" },
  },
  {
    label: "Prompt injection (LLM)",
    type: "llm_judge",
    config: { kind: "prompt_injection" },
  },
  {
    label: "Context precision (LLM)",
    type: "llm_judge",
    config: { kind: "context_precision" },
  },
  {
    label: "Context recall (LLM)",
    type: "llm_judge",
    config: { kind: "context_recall" },
  },
] as const;
