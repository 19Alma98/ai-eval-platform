"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api/client";
import type { ItemComparisonRow, MetricComparison } from "@/lib/api/types";
import { truncateId } from "@/lib/format";
import { withProjectQuery } from "@/lib/project-href";
import { CompareItemDetail } from "./compare-item-detail";
import { CompareStatusCell } from "./compare-table";
import {
  experimentCompareItemsQueryOptions,
  useEvaluators,
} from "./use-experiments";

const PREVIEW_MAX = 96;

function valuePreview(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function truncatePreview(text: string, max = PREVIEW_MAX): string {
  if (text === "—") return text;
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}

function formatScore(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(4);
}

function formatDelta(value: number | null): string {
  if (value === null || value === undefined) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(4)}`;
}

function hasResolvableOutput(row: ItemComparisonRow): boolean {
  return (
    row.baseline.actual_output != null || row.candidate.actual_output != null
  );
}

type EvaluatorOption = { id: string; name: string | null };

type CompareItemsTableProps = {
  projectId: string;
  experimentId: string;
  baselineId: string;
  metrics: MetricComparison[];
  candidateName?: string;
  baselineName?: string;
};

export function CompareItemsTable({
  projectId,
  experimentId,
  baselineId,
  metrics,
  candidateName,
  baselineName,
}: CompareItemsTableProps) {
  const evaluatorsQuery = useEvaluators(projectId);
  const [regressionsOnly, setRegressionsOnly] = useState(false);
  const [selectedEvaluatorId, setSelectedEvaluatorId] = useState<string>("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [detailRow, setDetailRow] = useState<ItemComparisonRow | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const evaluatorOptions: EvaluatorOption[] = useMemo(() => {
    const byId = new Map<string, string | null>();
    for (const m of metrics) {
      if (!byId.has(m.evaluator_id)) {
        byId.set(m.evaluator_id, m.evaluator_name);
      }
    }
    if (byId.size > 0) {
      return [...byId.entries()].map(([id, name]) => ({ id, name }));
    }
    return (evaluatorsQuery.data ?? []).map((ev) => ({
      id: ev.id,
      name: ev.name,
    }));
  }, [metrics, evaluatorsQuery.data]);

  const singleEvaluator = evaluatorOptions.length === 1;
  const needsExplicitEvaluator = evaluatorOptions.length > 1;

  useEffect(() => {
    if (evaluatorOptions.length === 0) {
      setSelectedEvaluatorId("");
      return;
    }
    if (singleEvaluator) {
      setSelectedEvaluatorId(evaluatorOptions[0].id);
      return;
    }
    setSelectedEvaluatorId((prev) => {
      if (prev && evaluatorOptions.some((o) => o.id === prev)) return prev;
      return evaluatorOptions[0]?.id ?? "";
    });
  }, [evaluatorOptions, singleEvaluator]);

  const queryReady =
    evaluatorOptions.length === 0 ||
    singleEvaluator ||
    Boolean(selectedEvaluatorId);

  const compareItemsOpts = useMemo(
    () => ({
      evaluatorId:
        needsExplicitEvaluator && selectedEvaluatorId
          ? selectedEvaluatorId
          : undefined,
      regressionsOnly,
    }),
    [needsExplicitEvaluator, selectedEvaluatorId, regressionsOnly],
  );

  const itemsQuery = useQuery({
    ...experimentCompareItemsQueryOptions(
      experimentId,
      baselineId,
      compareItemsOpts,
    ),
    enabled: Boolean(experimentId && baselineId && queryReady),
  });

  const rows = itemsQuery.data?.items ?? [];

  useEffect(() => {
    setSelectedIndex(0);
  }, [rows.length, regressionsOnly, selectedEvaluatorId]);

  const columns: DataTableColumn<ItemComparisonRow>[] = useMemo(
    () => [
      {
        id: "input",
        header: "Input",
        cell: (row) => (
          <span className="line-clamp-2 font-mono text-xs text-foreground">
            {truncatePreview(valuePreview(row.input))}
          </span>
        ),
      },
      {
        id: "baseline_output",
        header: "Baseline output",
        cell: (row) => (
          <span className="line-clamp-2 font-mono text-xs text-muted-foreground">
            {truncatePreview(valuePreview(row.baseline.actual_output))}
          </span>
        ),
      },
      {
        id: "candidate_output",
        header: "Candidate output",
        cell: (row) => (
          <span className="line-clamp-2 font-mono text-xs text-muted-foreground">
            {truncatePreview(valuePreview(row.candidate.actual_output))}
          </span>
        ),
      },
      {
        id: "baseline_score",
        header: "Base score",
        headerClassName: "w-[88px] text-right",
        className: "text-right font-mono tabular-nums text-sm text-muted-foreground",
        cell: (row) => formatScore(row.baseline.score),
      },
      {
        id: "candidate_score",
        header: "Cand score",
        headerClassName: "w-[88px] text-right",
        className: "text-right font-mono tabular-nums text-sm",
        cell: (row) => formatScore(row.candidate.score),
      },
      {
        id: "delta",
        header: "Delta",
        headerClassName: "w-[88px] text-right",
        className: "text-right font-mono tabular-nums text-sm",
        cell: (row) => formatDelta(row.delta),
      },
      {
        id: "status",
        header: "Status",
        headerClassName: "w-[112px]",
        cell: (row) => <CompareStatusCell status={row.status} />,
      },
    ],
    [],
  );

  const experimentDetailHref = withProjectQuery(
    `/experiments/${encodeURIComponent(experimentId)}`,
    projectId,
  );

  function openDetail(row: ItemComparisonRow) {
    setDetailRow(row);
    setDetailOpen(true);
  }

  return (
    <section className="mt-4 flex flex-col gap-3 border-t border-border pt-4">
      <h2 className="text-sm font-medium text-foreground">Item responses</h2>

      <div className="flex flex-wrap items-end gap-4">
        {!singleEvaluator && evaluatorOptions.length > 0 ? (
          <div className="flex flex-col gap-1 sm:min-w-[220px]">
            <label
              htmlFor="compare-items-evaluator"
              className="text-xs font-medium text-muted-foreground"
            >
              Evaluator
            </label>
            <Select
              value={selectedEvaluatorId}
              onValueChange={(v) => {
                if (v) setSelectedEvaluatorId(v);
              }}
              disabled={evaluatorsQuery.isLoading && evaluatorOptions.length === 0}
            >
              <SelectTrigger
                id="compare-items-evaluator"
                className="w-full sm:w-[260px]"
              >
                <SelectValue placeholder="Select evaluator" />
              </SelectTrigger>
              <SelectContent>
                {evaluatorOptions.map((opt) => (
                  <SelectItem key={opt.id} value={opt.id}>
                    {opt.name?.trim() || truncateId(opt.id, 10)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}

        <label className="flex cursor-pointer items-center gap-2 pb-2 text-sm text-foreground">
          <input
            type="checkbox"
            className="size-4 rounded border-border"
            checked={regressionsOnly}
            onChange={(e) => setRegressionsOnly(e.target.checked)}
          />
          Regressions only
        </label>
      </div>

      {evaluatorOptions.length === 0 &&
      !evaluatorsQuery.isLoading &&
      !itemsQuery.isFetching &&
      !itemsQuery.data ? (
        <EmptyState
          title="No evaluation runs yet"
          description="Run evaluators on both experiments before comparing item-level responses."
          action={
            <Link
              href={experimentDetailHref}
              className="text-sm font-medium text-foreground underline-offset-4 hover:underline"
            >
              Open experiment to evaluate
            </Link>
          }
        />
      ) : itemsQuery.isLoading ? (
        <LoadingBlock className="min-h-[160px]" />
      ) : itemsQuery.isError ? (
        <CompareItemsError
          error={itemsQuery.error}
          onRetry={() => itemsQuery.refetch()}
        />
      ) : rows.length === 0 ? (
        regressionsOnly ? (
          <EmptyState
            title="No regressions"
            description="No items regressed for this evaluator with the current filter."
          />
        ) : (
          <EmptyState
            title="No dataset items"
            description="This dataset has no cases to compare."
          />
        )
      ) : !rows.some(hasResolvableOutput) ? (
        <EmptyState
          title="No agent responses to show"
          description="Upload per-experiment outputs before evaluate, or set actual_output on dataset items (legacy). Use PUT /api/v1/experiments/{experiment_id}/outputs with dataset_item_id, actual_output, and optional context."
        />
      ) : (
        <>
          {rows.every((r) => r.status === "unavailable") ? (
            <p className="text-sm text-muted-foreground">
              Scores are unavailable for this evaluator — run evaluate on both
              experiments to compare per-item deltas.{" "}
              <Link
                href={experimentDetailHref}
                className="font-medium text-foreground underline-offset-4 hover:underline"
              >
                Open experiment
              </Link>
            </p>
          ) : null}
          <DataTable
            rows={rows}
            columns={columns}
            getRowKey={(row) => row.dataset_item_id}
            selectedIndex={Math.min(selectedIndex, Math.max(rows.length - 1, 0))}
            onSelectedIndexChange={setSelectedIndex}
            onRowActivate={(row) => openDetail(row)}
            aria-label="Experiment item response comparison"
          />
          <CompareItemDetail
            row={detailRow}
            open={detailOpen}
            onOpenChange={setDetailOpen}
            baselineLabel={baselineName}
            candidateLabel={candidateName}
          />
        </>
      )}
    </section>
  );
}

function CompareItemsError({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : "Unknown error";

  const isDatasetMismatch =
    error instanceof ApiError &&
    error.status === 400 &&
    message.toLowerCase().includes("different datasets");

  const isAmbiguousEvaluator =
    error instanceof ApiError &&
    error.status === 400 &&
    message.toLowerCase().includes("evaluator_id");

  if (isDatasetMismatch) {
    return (
      <ErrorState
        title="Different datasets"
        message="These experiments are not on the same dataset, so item-level compare is not available."
      />
    );
  }

  if (isAmbiguousEvaluator) {
    return (
      <ErrorState
        title="Choose an evaluator"
        message="Multiple evaluators have runs on these experiments. Select one from the list above."
      />
    );
  }

  return (
    <ErrorState
      title="Could not load item responses"
      message={
        error instanceof ApiError
          ? `${error.status}: ${message}`
          : message
      }
      onRetry={onRetry}
    />
  );
}
