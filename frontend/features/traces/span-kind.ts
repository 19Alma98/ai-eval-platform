export function kindBarClass(kind: string): string {
  const k = kind.toUpperCase();
  if (k === "LLM") return "bg-kind-llm/35 border-kind-llm/50";
  if (k === "CHAIN") return "bg-kind-chain/35 border-kind-chain/50";
  if (k === "RETRIEVER") return "bg-kind-retriever/35 border-kind-retriever/50";
  if (k === "TOOL") return "bg-kind-tool/35 border-kind-tool/50";
  return "bg-kind-other/35 border-kind-other/50";
}

export function kindTextClass(kind: string): string {
  const k = kind.toUpperCase();
  if (k === "LLM") return "text-kind-llm";
  if (k === "CHAIN") return "text-kind-chain";
  if (k === "RETRIEVER") return "text-kind-retriever";
  if (k === "TOOL") return "text-kind-tool";
  return "text-kind-other";
}
