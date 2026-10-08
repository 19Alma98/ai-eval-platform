import type {
  DatasetItem,
  EvaluationResult,
  ExperimentItemOutput,
} from "@/lib/api/types";

export function shouldRenderRunItemsSection(_opts: {
  hasEvaluationRun: boolean;
}): boolean {
  return true;
}

export type RunItemView = {
  datasetItemId: string;
  question: unknown;
  expectedAnswer: unknown | null;
  expectedDocIds: string[];
  retrievedDocuments: unknown | null;
  actualOutput: unknown | null;
  context: unknown | null;
  score: number | null;
  label: string | null;
  explanation: string | null;
  resultMetadata: Record<string, unknown>;
  sourceTraceId: string | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseExpectedDocIds(metadata: Record<string, unknown>): string[] {
  const raw = metadata.expected_doc_ids;
  if (Array.isArray(raw)) {
    return raw.filter((id): id is string => typeof id === "string");
  }
  if (typeof raw === "string" && raw.trim()) {
    return raw
      .split(/[,;\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return [];
}

function resolveActualAndContext(
  item: DatasetItem,
  output: ExperimentItemOutput | undefined,
): { actualOutput: unknown | null; context: unknown | null } {
  if (!output) {
    return { actualOutput: item.actual_output, context: item.context };
  }
  const actualOutput =
    output.actual_output !== null && output.actual_output !== undefined
      ? output.actual_output
      : item.actual_output;
  const context =
    output.context !== null && output.context !== undefined
      ? output.context
      : item.context;
  return { actualOutput, context };
}

function resolveSourceTraceId(
  item: DatasetItem,
  output: ExperimentItemOutput | undefined,
): string | null {
  const fromOutput = output?.metadata?.source_trace_id;
  if (typeof fromOutput === "string" && fromOutput.trim()) {
    return fromOutput.trim();
  }
  if (item.source_trace_id?.trim()) return item.source_trace_id.trim();
  return null;
}

function retrievedDocumentsFromContext(context: unknown | null): unknown | null {
  if (!isRecord(context)) return null;
  if ("documents" in context) return context.documents ?? null;
  return null;
}

export function buildRunItemViews(
  datasetItems: DatasetItem[],
  outputs: ExperimentItemOutput[],
  results: EvaluationResult[],
): RunItemView[] {
  const outputByItem = new Map(outputs.map((o) => [o.dataset_item_id, o]));
  const resultByItem = new Map(results.map((r) => [r.dataset_item_id, r]));

  return datasetItems.map((item) => {
    const output = outputByItem.get(item.id);
    const result = resultByItem.get(item.id);
    const { actualOutput, context } = resolveActualAndContext(item, output);
    const metadata = item.metadata ?? {};

    return {
      datasetItemId: item.id,
      question: item.input,
      expectedAnswer: item.expected_output,
      expectedDocIds: parseExpectedDocIds(metadata),
      retrievedDocuments: retrievedDocumentsFromContext(context),
      actualOutput,
      context,
      score: result?.score ?? null,
      label: result?.label ?? null,
      explanation: result?.explanation ?? null,
      resultMetadata: result?.metadata ?? {},
      sourceTraceId: resolveSourceTraceId(item, output),
    };
  });
}
