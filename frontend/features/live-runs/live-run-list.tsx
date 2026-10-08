"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { liveJudgeWarningMessage } from "@/features/judges/judge-metadata";
import type { JudgeCalibrationBucket, LiveInteraction } from "@/lib/api/types";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { useLiveJudgeCalibration, useLiveRuns } from "./use-live-runs";

function primaryScore(row: LiveInteraction): string {
  const grounded = row.scores.find((s) => s.kind === "groundedness");
  const score = grounded ?? row.scores[0];
  if (!score || score.score == null) return "—";
  return score.score.toFixed(2);
}

function reviewSummary(row: LiveInteraction): string {
  const reviewed = row.scores.filter((s) => s.review);
  if (reviewed.length === 0) {
    return row.review?.verdict ?? "—";
  }
  const agrees = reviewed.filter((s) => s.review?.verdict === "agree").length;
  return `${agrees}/${reviewed.length} agree`;
}

function pct(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

export function LiveRunList() {
  const router = useRouter();
  const { projectId } = useProjectId();
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [calibrationIndex, setCalibrationIndex] = useState(0);
  const [judgeStatus, setJudgeStatus] = useState<string>("");
  const [failedOnly, setFailedOnly] = useState(false);
  const [search, setSearch] = useState("");
  const query = useLiveRuns(projectId, {
    judgeStatus: judgeStatus || undefined,
    failedOnly: failedOnly || undefined,
    search: search.trim() || undefined,
  });
  const calibration = useLiveJudgeCalibration(projectId);

  const rows = query.data?.items ?? [];
  const unsuitableMessage = liveJudgeWarningMessage(query.data?.judge_warnings);
  const calibrationRows = calibration.data ?? [];

  const calibrationColumns: DataTableColumn<JudgeCalibrationBucket>[] = useMemo(
    () => [
      {
        id: "kind",
        header: "Kind",
        cell: (row) => row.kind,
      },
      {
        id: "model",
        header: "Model",
        cell: (row) => row.model ?? "—",
      },
      {
        id: "n",
        header: "n",
        headerClassName: "w-[64px]",
        className: "font-mono tabular-nums",
        cell: (row) => String(row.n_reviewed),
      },
      {
        id: "agreement",
        header: "Agreement",
        headerClassName: "w-[100px]",
        className: "font-mono tabular-nums",
        cell: (row) => pct(row.agreement_rate),
      },
      {
        id: "edits",
        header: "Expl. edits",
        headerClassName: "w-[100px]",
        className: "font-mono tabular-nums",
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
        headerClassName: "w-[120px]",
        cell: (row) => <RelativeTime date={row.created_at} />,
      },
      {
        id: "question",
        header: "Question",
        cell: (row) => (
          <span className="line-clamp-2 text-foreground">{row.question}</span>
        ),
      },
      {
        id: "status",
        header: "Judge",
        headerClassName: "w-[100px]",
        cell: (row) => <StatusBadge status={row.judge_status} />,
      },
      {
        id: "score",
        header: "Score",
        headerClassName: "w-[80px]",
        className: "font-mono tabular-nums",
        cell: (row) => primaryScore(row),
      },
      {
        id: "review",
        header: "Review",
        headerClassName: "w-[120px]",
        cell: (row) => {
          const summary = reviewSummary(row);
          if (summary === "—") {
            return <span className="text-muted-foreground">—</span>;
          }
          return <Badge variant="outline">{summary}</Badge>;
        },
      },
    ],
    [],
  );

  if (query.isLoading) return <LoadingBlock />;
  if (query.isError) {
    return <ErrorState message="Could not load live runs." />;
  }

  return (
    <div className="space-y-3">
      {unsuitableMessage ? (
        <div className="rounded-md border border-status-warn bg-status-warn-bg px-3 py-2 text-sm text-status-warn">
          {unsuitableMessage}
        </div>
      ) : null}
      {calibrationRows.length > 0 ? (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-foreground">
            Judge calibration
          </h2>
          <p className="text-xs text-muted-foreground">
            Human agree/disagree with judge PASS/FAIL, by kind and model (last
            90 days).
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
            aria-label="Judge calibration"
          />
        </section>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Search question…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <select
          className="h-9 rounded-md border border-border bg-background px-2 text-sm"
          value={judgeStatus}
          onChange={(e) => setJudgeStatus(e.target.value)}
        >
          <option value="">All statuses</option>
          <option value="pending">pending</option>
          <option value="running">running</option>
          <option value="scored">scored</option>
          <option value="error">error</option>
        </select>
        <Button
          type="button"
          variant={failedOnly ? "default" : "outline"}
          size="sm"
          onClick={() => setFailedOnly((v) => !v)}
        >
          Failed only
        </Button>
      </div>
      {rows.length === 0 ? (
        <EmptyState
          title="No live runs yet"
          description="Submit interactions from production via client.live_runs.submit(...)."
        />
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          getRowKey={(row) => row.id}
          selectedIndex={selectedIndex}
          onSelectedIndexChange={setSelectedIndex}
          onRowActivate={onRowActivate}
          aria-label="Live runs"
        />
      )}
    </div>
  );
}
