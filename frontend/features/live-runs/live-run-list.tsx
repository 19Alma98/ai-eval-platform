"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useCallback, useMemo, useState, type ReactNode } from "react";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RelativeTime } from "@/components/relative-time";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { liveJudgeWarningMessage } from "@/features/judges/judge-metadata";
import type { JudgeCalibrationBucket, LiveInteraction } from "@/lib/api/types";
import { formatErrorForUi } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { formatScore } from "@/lib/format";
import { metricLabel } from "@/lib/metrics-catalog";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { LIVE_VERDICT_LABELS, liveVerdict, type LiveVerdict } from "./live-verdict";
import { feedbackThumb } from "./trace-feedback";
import { useLiveJudgeCalibration, useLiveRuns } from "./use-live-runs";

const VERDICT_STYLES: Record<LiveVerdict, string> = {
  passing: "bg-status-ok-bg text-status-ok",
  failing: "bg-status-fail-bg text-status-fail",
  waiting: "bg-status-unset-bg text-status-unset",
  error: "bg-status-warn-bg text-status-warn",
  not_scored: "bg-status-unset-bg text-status-unset",
};

function ScoreChips({ row }: { row: LiveInteraction }) {
  const scored = row.scores.filter((s) => s.score != null);
  if (scored.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {scored.map((s) => {
        const fail = (s.label ?? "").toUpperCase() === "FAIL";
        return (
          <span
            key={s.id}
            className={cn(
              "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs",
              fail ? "bg-status-fail-bg text-status-fail" : "bg-surface-2 text-foreground",
            )}
          >
            {metricLabel(s.kind)}
            <span className="tabular-nums font-medium">{formatScore(s.score)}</span>
          </span>
        );
      })}
    </span>
  );
}

function reviewSummary(row: LiveInteraction): string | null {
  const reviewed = row.scores.filter((s) => s.review);
  if (reviewed.length === 0) return null;
  const agrees = reviewed.filter((s) => s.review?.verdict === "agree").length;
  return agrees === reviewed.length
    ? "Judge confirmed"
    : `${reviewed.length - agrees} disagreement${reviewed.length - agrees === 1 ? "" : "s"}`;
}

type Filter = "all" | "failing" | "waiting";

function pct(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

export function LiveRunList() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { projectId } = useProjectId();
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [calibrationIndex, setCalibrationIndex] = useState(0);
  const [filter, setFilter] = useState<Filter>(() =>
    searchParams.get("failed") === "1" ? "failing" : "all",
  );
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search.trim());
  const query = useLiveRuns(projectId, {
    // "Waiting" covers both queued and in-flight judge runs.
    judgeStatus: filter === "waiting" ? "pending,running" : undefined,
    failedOnly: filter === "failing" || undefined,
    search: debouncedSearch || undefined,
  });
  const calibration = useLiveJudgeCalibration(projectId);

  const rows = query.data?.items ?? [];
  const unsuitableMessage = liveJudgeWarningMessage(query.data?.judge_warnings);
  const calibrationRows = calibration.data ?? [];

  const calibrationColumns: DataTableColumn<JudgeCalibrationBucket>[] = useMemo(
    () => [
      {
        id: "kind",
        header: "Metric",
        cell: (row) => metricLabel(row.kind),
      },
      {
        id: "model",
        header: "Judge model",
        cell: (row) => row.model ?? "—",
      },
      {
        id: "n",
        header: "Reviews",
        headerClassName: "w-[90px]",
        className: "tabular-nums",
        cell: (row) => String(row.n_reviewed),
      },
      {
        id: "agreement",
        header: "Humans agree",
        headerClassName: "w-[120px]",
        className: "tabular-nums",
        cell: (row) => (
          <span className={cn(row.agreement_rate < 0.8 && "font-medium text-status-warn")}>
            {pct(row.agreement_rate)}
          </span>
        ),
      },
      {
        id: "edits",
        header: "Explanations edited",
        headerClassName: "w-[160px]",
        className: "tabular-nums",
        cell: (row) => pct(row.explanation_edit_rate),
      },
    ],
    [],
  );

  const onRowActivate = useCallback(
    (row: LiveInteraction) => {
      if (!projectId) return;
      router.push(
        withProjectQuery(`/live-runs/${encodeURIComponent(row.id)}`, projectId),
      );
    },
    [projectId, router],
  );

  const columns: DataTableColumn<LiveInteraction>[] = useMemo(
    () => [
      {
        id: "created",
        header: "When",
        headerClassName: "w-[130px]",
        className: "text-muted-foreground",
        cell: (row) => <RelativeTime date={row.created_at} />,
      },
      {
        id: "question",
        header: "Question and answer",
        wrap: true,
        cell: (row) => (
          <span className="flex flex-col">
            <span className="line-clamp-1 font-medium text-foreground">{row.question}</span>
            <span className="line-clamp-1 text-xs text-muted-foreground">{row.answer}</span>
          </span>
        ),
      },
      {
        id: "verdict",
        header: "Verdict",
        headerClassName: "w-[150px]",
        cell: (row) => {
          const verdict = liveVerdict(row);
          const thumb = feedbackThumb(row.trace_scores);
          return (
            <span className="inline-flex items-center gap-1.5">
              <span
                className={cn(
                  "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium",
                  VERDICT_STYLES[verdict],
                )}
              >
                {LIVE_VERDICT_LABELS[verdict]}
              </span>
              {thumb === "up" ? (
                <ThumbsUp
                  role="img"
                  className="size-3.5 text-status-ok"
                  aria-label="Thumbs-up feedback"
                />
              ) : thumb === "down" ? (
                <ThumbsDown
                  role="img"
                  className="size-3.5 text-status-fail"
                  aria-label="Thumbs-down feedback"
                />
              ) : null}
            </span>
          );
        },
      },
      {
        id: "scores",
        header: "Scores",
        headerClassName: "w-[300px]",
        wrap: true,
        cell: (row) => <ScoreChips row={row} />,
      },
      {
        id: "review",
        header: "Human review",
        headerClassName: "w-[150px]",
        cell: (row) => {
          const summary = reviewSummary(row);
          if (!summary) return <span className="text-muted-foreground">Not reviewed</span>;
          return <Badge variant="outline">{summary}</Badge>;
        },
      },
    ],
    [],
  );

  const filtersActive = filter !== "all" || debouncedSearch !== "";
  // Only the table reacts to loading/errors so the toolbar (and the search
  // field's focus) survives every refetch.
  const staleError = query.isError && query.data != null;

  let table: ReactNode;
  if (query.isLoading) {
    table = <LoadingBlock />;
  } else if (query.isError && !query.data) {
    table = (
      <ErrorState
        title="Could not load live traffic"
        message={formatErrorForUi(query.error)}
        onRetry={() => void query.refetch()}
      />
    );
  } else if (rows.length === 0) {
    table = filtersActive ? (
      <EmptyState
        title="Nothing matches"
        description="No live answers match these filters."
      />
    ) : (
      <EmptyState
        title="No live traffic yet"
        description="Send real questions and answers from your app with client.live_runs.submit(project_id, question=…, answer=…, documents=[…]). Each one is scored automatically."
      />
    );
  } else {
    table = (
      <DataTable
        rows={rows}
        columns={columns}
        getRowKey={(row) => row.id}
        selectedIndex={selectedIndex}
        onSelectedIndexChange={setSelectedIndex}
        onRowActivate={onRowActivate}
        aria-label="Live answers"
        className={cn(query.isPlaceholderData && "opacity-60")}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {unsuitableMessage ? (
        <div className="rounded-md border border-status-warn bg-status-warn-bg px-3 py-2 text-sm text-status-warn">
          <strong>Judge results may be unreliable.</strong> {unsuitableMessage}
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <div role="radiogroup" aria-label="Filter live answers" className="flex rounded-md border border-border bg-surface p-0.5">
          {(
            [
              ["all", "All"],
              ["failing", "Failing"],
              ["waiting", "Waiting for judge"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={filter === key}
              onClick={() => setFilter(key)}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground",
                filter === key && "bg-row-selected text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <Input
          type="search"
          placeholder="Search questions…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-8 max-w-xs"
          aria-label="Search questions"
        />
      </div>
      {staleError ? (
        <div
          role="status"
          className="flex items-center justify-between gap-3 rounded-md border border-status-warn bg-status-warn-bg px-3 py-2 text-sm text-status-warn"
        >
          <span>
            Could not refresh live traffic — showing the last loaded results.{" "}
            {formatErrorForUi(query.error)}
          </span>
          <button
            type="button"
            className="shrink-0 font-medium underline"
            onClick={() => void query.refetch()}
          >
            Retry
          </button>
        </div>
      ) : null}
      {table}
      {calibrationRows.length > 0 ? (
        <details className="rounded-lg border border-border bg-surface px-4 py-3">
          <summary className="cursor-pointer text-sm font-medium text-foreground">
            How reliable is the judge?
          </summary>
          <p className="mt-2 mb-3 text-xs text-muted-foreground">
            How often reviewers agreed with the judge&apos;s pass/fail verdict in the
            last 90 days. Below 80% means the judge needs attention.
          </p>
          <DataTable
            rows={calibrationRows}
            columns={calibrationColumns}
            getRowKey={(row) =>
              `${row.kind}|${row.model ?? ""}|${row.method ?? ""}|${row.prompt_version ?? ""}`
            }
            selectedIndex={calibrationIndex}
            onSelectedIndexChange={setCalibrationIndex}
            onRowActivate={() => undefined}
            aria-label="Judge reliability"
          />
        </details>
      ) : null}
    </div>
  );
}
