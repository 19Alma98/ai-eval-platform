"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { ApiError, formatErrorForUi } from "@/lib/api/client";
import type { ItemComparisonRow, MetricComparison } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatScore, resolveLabel } from "@/lib/format";
import { metricLabel } from "@/lib/metrics-catalog";
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

function formatDelta(value: number | null): string {
  if (value === null || value === undefined) return "—";
  if (Math.abs(value) < 0.005) return "±0";
  const sign = value > 0 ? "+" : "−";
  return `${sign}${Math.abs(value).toFixed(2)}`;
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
  /** Metric picked in the summary table above. */
  evaluatorId: string | null;
};

export function CompareItemsTable({
  projectId,
  experimentId,
  baselineId,
  metrics,
  candidateName,
  baselineName,
  evaluatorId,
}: CompareItemsTableProps) {
  const evaluatorsQuery = useEvaluators(projectId);
  const [changeFilter, setChangeFilter] = useState<"all" | "worse" | "better">("all");
  const regressionsOnly = changeFilter === "worse";
  const userEvaluatorId = evaluatorId ?? "";
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [detailRow, setDetailRow] = useState<ItemComparisonRow | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const evaluatorNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const ev of evaluatorsQuery.data ?? []) {
      map.set(ev.id, ev.name);
    }
    return map;
  }, [evaluatorsQuery.data]);

  const evaluatorOptions: EvaluatorOption[] = useMemo(() => {
    const byId = new Map<string, string | null>();
    for (const m of metrics) {
      if (!byId.has(m.evaluator_id)) {
        byId.set(m.evaluator_id, m.evaluator_name);
      }
    }
    if (byId.size > 0) {
      return [...byId.entries()].map(([id, name]) => ({
        id,
        name:
          name?.trim() ||
          resolveLabel(id, evaluatorNameById, "Unknown evaluator"),
      }));
    }
    return (evaluatorsQuery.data ?? []).map((ev) => ({
      id: ev.id,
      name: ev.name,
    }));
  }, [metrics, evaluatorsQuery.data, evaluatorNameById]);

  const singleEvaluator = evaluatorOptions.length === 1;
  const needsExplicitEvaluator = evaluatorOptions.length > 1;

  const selectedEvaluatorId = useMemo(() => {
    if (evaluatorOptions.length === 0) return "";
    if (singleEvaluator) return evaluatorOptions[0].id;
    if (
      userEvaluatorId &&
      evaluatorOptions.some((o) => o.id === userEvaluatorId)
    ) {
      return userEvaluatorId;
    }
    return evaluatorOptions[0]?.id ?? "";
  }, [evaluatorOptions, singleEvaluator, userEvaluatorId]);

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

  const fetchedRows = itemsQuery.data?.items ?? [];
  const rows =
    changeFilter === "better"
      ? fetchedRows.filter((r) => r.status === "improved")
      : fetchedRows;

  const itemsListResetKey = `${rows.length}:${changeFilter}:${selectedEvaluatorId}`;
  const [prevItemsListResetKey, setPrevItemsListResetKey] =
    useState(itemsListResetKey);
  if (itemsListResetKey !== prevItemsListResetKey) {
    setPrevItemsListResetKey(itemsListResetKey);
    setSelectedIndex(0);
  }

  const columns: DataTableColumn<ItemComparisonRow>[] = useMemo(
    () => [
      {
        id: "input",
        header: "Question",
        wrap: true,
        cell: (row) => (
          <span className="line-clamp-2 text-foreground">
            {valuePreview(row.input)}
          </span>
        ),
      },
      {
        id: "baseline_output",
        header: "Baseline answer",
        wrap: true,
        cell: (row) => (
          <span className="line-clamp-2 text-muted-foreground">
            {truncatePreview(valuePreview(row.baseline.actual_output))}
          </span>
        ),
      },
      {
        id: "candidate_output",
        header: "Candidate answer",
        wrap: true,
        cell: (row) => (
          <span className="line-clamp-2 text-muted-foreground">
            {truncatePreview(valuePreview(row.candidate.actual_output))}
          </span>
        ),
      },
      {
        id: "scores",
        header: "Score",
        headerClassName: "w-[120px] text-right",
        className: "text-right tabular-nums text-sm",
        cell: (row) => (
          <span>
            <span className="text-muted-foreground">{formatScore(row.baseline.score)}</span>
            {" → "}
            <span className="font-medium text-foreground">{formatScore(row.candidate.score)}</span>
          </span>
        ),
      },
      {
        id: "delta",
        header: "Change",
        headerClassName: "w-[80px] text-right",
        className: "text-right tabular-nums text-sm",
        cell: (row) => (
          <span
            className={cn(
              row.delta != null && row.delta < -0.005 && "text-status-fail",
              row.delta != null && row.delta > 0.005 && "text-status-ok",
            )}
          >
            {formatDelta(row.delta)}
          </span>
        ),
      },
      {
        id: "status",
        header: "Verdict",
        headerClassName: "w-[130px]",
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
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col">
          <h2 className="font-serif text-lg font-medium text-foreground">
            Answers side by side
          </h2>
          <p className="text-sm text-muted-foreground">
            Scores for{" "}
            <span className="font-medium text-foreground">
              {metricLabel(
                evaluatorOptions.find((o) => o.id === selectedEvaluatorId)?.name,
              )}
            </span>
            . Pick another metric in the table above. Click a row to read both answers.
          </p>
        </div>
        <div
          role="radiogroup"
          aria-label="Show answers"
          className="flex rounded-md border border-border bg-surface p-0.5"
        >
          {(
            [
              ["all", "All answers"],
              ["worse", "Got worse"],
              ["better", "Got better"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={changeFilter === key}
              onClick={() => setChangeFilter(key)}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground",
                changeFilter === key && "bg-row-selected text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {evaluatorOptions.length === 0 &&
      !evaluatorsQuery.isLoading &&
      !itemsQuery.isFetching &&
      !itemsQuery.data ? (
        <EmptyState
          title="Not scored yet"
          description="Score the answers of both experiments to compare them question by question."
          action={
            <Link
              href={experimentDetailHref}
              className="text-sm font-medium text-foreground underline-offset-4 hover:underline"
            >
              Open experiment
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
        changeFilter !== "all" ? (
          <EmptyState
            title={changeFilter === "worse" ? "Nothing got worse" : "Nothing got better"}
            description={
              changeFilter === "worse"
                ? "No answer scores lower than in the baseline for this metric."
                : "No answer scores higher than in the baseline for this metric."
            }
          />
        ) : (
          <EmptyState
            title="No questions"
            description="This test set has no questions to compare."
          />
        )
      ) : !rows.some(hasResolvableOutput) ? (
        <EmptyState
          title="No answers yet"
          description="Run your app on the test set for both experiments, then score them."
          action={
            <Link
              href={experimentDetailHref}
              className="text-sm font-medium text-foreground underline-offset-4 hover:underline"
            >
              Open experiment
            </Link>
          }
        />
      ) : (
        <>
          {rows.every((r) => r.status === "unavailable") ? (
            <p className="text-sm text-muted-foreground">
              This metric was not scored on both experiments.{" "}
              <Link
                href={experimentDetailHref}
                className="font-medium text-foreground underline-offset-4 hover:underline"
              >
                Open experiment
              </Link>
            </p>
          ) : null}
          {rows.some((r) => r.status === "config_mismatch") ? (
            <p className="text-sm text-status-warn">
              The two experiments were scored with different settings for this
              metric (for example a different judge model), so the scores are not
              comparable. Re-score both with the same metrics.
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
  const message = formatErrorForUi(error);

  const isDatasetMismatch =
    error instanceof ApiError &&
    error.status === 400 &&
    (message.includes("Runs must share the same dataset (test set version)") ||
      message.toLowerCase().includes("different datasets"));

  const isAmbiguousEvaluator =
    error instanceof ApiError &&
    error.status === 400 &&
    message.toLowerCase().includes("evaluator_id");

  if (isDatasetMismatch) {
    return (
      <ErrorState
        title="Different test sets"
        message="Both experiments must use the same test set version. Pick a baseline that ran on the same test set."
      />
    );
  }

  if (isAmbiguousEvaluator) {
    return (
      <ErrorState
        title="Choose a metric"
        message="Select a metric in the table above to compare answers."
      />
    );
  }

  return (
    <ErrorState
      title="Could not load answers"
      message={message}
      onRetry={onRetry}
    />
  );
}
