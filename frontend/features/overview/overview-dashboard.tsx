"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { PageIntro } from "@/components/page-intro";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { formatErrorForUi } from "@/lib/api/client";
import type { Experiment, LiveInteraction } from "@/lib/api/types";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { cn } from "@/lib/cn";
import {
  evaluatorsQueryKey,
  experimentsQueryKey,
  useEvaluators,
  useExperiments,
} from "@/features/experiments/use-experiments";
import {
  datasetsQueryKey,
  useDatasets,
} from "@/features/datasets/use-datasets";
import {
  liveRunsQueryKey,
  useLiveRuns,
} from "@/features/live-runs/use-live-runs";
import { LoopProgress } from "@/features/overview/loop-progress";

function isFailedLiveRun(row: LiveInteraction): boolean {
  return row.scores.some(
    (s) =>
      s.label === "FAIL" ||
      (s.threshold != null && s.score != null && s.score < s.threshold),
  );
}

function truncateQuestion(question: string, maxLen = 80): string {
  if (question.length <= maxLen) return question;
  return `${question.slice(0, maxLen)}…`;
}

function KpiStrip({
  label,
  value,
  href,
  subLink,
  className,
}: {
  label: string;
  value: React.ReactNode;
  href?: string;
  subLink?: { label: string; href: string };
  className?: string;
}) {
  const inner = (
    <>
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-lg tabular-nums text-foreground">
        {value}
      </p>
      {subLink ? (
        <Link
          href={subLink.href}
          className="mt-1 inline-block text-xs text-primary hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          {subLink.label}
        </Link>
      ) : null}
    </>
  );

  const shellClass = cn(
    "rounded-md border border-border bg-surface px-3 py-2.5 transition-colors",
    href && "hover:bg-row-hover cursor-pointer",
    className,
  );

  if (href) {
    return (
      <Link href={href} className={shellClass}>
        {inner}
      </Link>
    );
  }

  return <div className={shellClass}>{inner}</div>;
}

export function OverviewDashboard() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { projectId } = useProjectId();

  const [liveSelectedIndex, setLiveSelectedIndex] = useState(0);
  const [experimentSelectedIndex, setExperimentSelectedIndex] = useState(0);

  const liveQuery = useLiveRuns(projectId);
  const datasetsQuery = useDatasets(projectId);
  const experimentsQuery = useExperiments(projectId);
  const evaluatorsQuery = useEvaluators(projectId);

  const liveItems = useMemo(
    () => liveQuery.data?.items ?? [],
    [liveQuery.data?.items],
  );
  const datasets = useMemo(
    () => datasetsQuery.data ?? [],
    [datasetsQuery.data],
  );
  const experiments = useMemo(
    () => experimentsQuery.data ?? [],
    [experimentsQuery.data],
  );

  const projectQuery = projectId ? `?project=${encodeURIComponent(projectId)}` : "";

  const liveTotal = liveItems.length;
  const livePending = useMemo(
    () =>
      liveItems.filter(
        (r) => r.judge_status === "pending" || r.judge_status === "running",
      ).length,
    [liveItems],
  );
  const liveFailed = useMemo(
    () => liveItems.filter(isFailedLiveRun).length,
    [liveItems],
  );

  const recentLiveRuns = useMemo(
    () =>
      [...liveItems]
        .sort(
          (a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
        )
        .slice(0, 10),
    [liveItems],
  );

  const latestExperiments = useMemo(
    () =>
      [...experiments]
        .sort(
          (a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
        )
        .slice(0, 5),
    [experiments],
  );

  const hasCompletedExperiment = useMemo(
    () => experiments.some((e) => e.status === "completed"),
    [experiments],
  );

  const latestExperiment = useMemo(() => {
    if (experiments.length === 0) return null;
    return [...experiments].sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )[0];
  }, [experiments]);

  const loopCards = useMemo(() => {
    const datasetCount = datasets.length;
    const evaluatorCount = evaluatorsQuery.data?.length ?? 0;
    const experimentCount = experiments.length;

    return [
      {
        title: "Test set",
        measure: "Reusable test cases (input + expected/actual).",
        status: datasetCount === 0 ? ("empty" as const) : ("ready" as const),
        summary:
          datasetCount === 0
            ? "No test sets yet."
            : `${datasetCount} test set${datasetCount === 1 ? "" : "s"}`,
        href: "/datasets",
        cta: datasetCount === 0 ? "Create test set" : "Open test set",
      },
      {
        title: "Metrics",
        measure: "Evaluator packs — what you measure on each run.",
        status: evaluatorCount === 0 ? ("empty" as const) : ("ready" as const),
        summary:
          evaluatorCount === 0
            ? "No evaluators configured yet."
            : `${evaluatorCount} evaluator${evaluatorCount === 1 ? "" : "s"}`,
        href: "/metrics",
        cta: evaluatorCount === 0 ? "Configure Metrics" : "Open Metrics",
      },
      {
        title: "Runs",
        measure: "Evaluation runs — scores per evaluator.",
        status: experimentCount === 0 ? ("empty" as const) : ("ready" as const),
        summary:
          experimentCount === 0
            ? "No runs yet."
            : latestExperiment
              ? `${experimentCount} run${experimentCount === 1 ? "" : "s"}. Latest: ${latestExperiment.status}`
              : `${experimentCount} run${experimentCount === 1 ? "" : "s"}`,
        href: "/experiments",
        cta: experimentCount === 0 ? "Create run" : "Open runs",
      },
      {
        title: "Release readiness",
        measure: "PASS/FAIL against YAML thresholds.",
        status: hasCompletedExperiment ? ("ready" as const) : ("empty" as const),
        summary: hasCompletedExperiment
          ? "At least one completed run — ready to run release check."
          : "Complete a run before running release check.",
        href: "/release",
        cta: "Open release",
      },
    ];
  }, [
    datasets.length,
    evaluatorsQuery.data?.length,
    experiments.length,
    latestExperiment,
    hasCompletedExperiment,
  ]);

  const dataUpdatedAt = Math.max(
    liveQuery.dataUpdatedAt ?? 0,
    datasetsQuery.dataUpdatedAt ?? 0,
    experimentsQuery.dataUpdatedAt ?? 0,
    evaluatorsQuery.dataUpdatedAt ?? 0,
  );

  const onRefresh = useCallback(async () => {
    if (!projectId) return;
    await Promise.all([
      queryClient.refetchQueries({
        queryKey: liveRunsQueryKey(projectId),
      }),
      queryClient.refetchQueries({
        queryKey: datasetsQueryKey(projectId),
      }),
      queryClient.refetchQueries({
        queryKey: experimentsQueryKey(projectId),
      }),
      queryClient.refetchQueries({
        queryKey: evaluatorsQueryKey(projectId),
      }),
    ]);
  }, [projectId, queryClient]);

  const liveColumns: DataTableColumn<LiveInteraction>[] = useMemo(
    () => [
      {
        id: "question",
        header: "Question",
        cell: (row) => (
          <span className="font-medium text-foreground">
            {truncateQuestion(row.question)}
          </span>
        ),
      },
      {
        id: "status",
        header: "Judge",
        headerClassName: "w-[100px]",
        cell: (row) => <StatusBadge status={row.judge_status} />,
      },
      {
        id: "created_at",
        header: "Created",
        headerClassName: "w-[120px]",
        cell: (row) => <RelativeTime date={row.created_at} />,
      },
    ],
    [],
  );

  const experimentColumns: DataTableColumn<Experiment>[] = useMemo(
    () => [
      {
        id: "name",
        header: "Name",
        cell: (row) => (
          <span className="font-medium text-foreground">{row.name}</span>
        ),
      },
      {
        id: "status",
        header: "Status",
        headerClassName: "w-[120px]",
        cell: (row) => <StatusBadge status={row.status} />,
      },
      {
        id: "created_at",
        header: "Created",
        headerClassName: "w-[120px]",
        cell: (row) => <RelativeTime date={row.created_at} />,
      },
    ],
    [],
  );

  const onLiveActivate = useCallback(
    (row: LiveInteraction) => {
      if (!projectId) return;
      router.push(
        withProjectQuery(`/live-runs/${encodeURIComponent(row.id)}`, projectId),
      );
    },
    [projectId, router],
  );

  const onExperimentActivate = useCallback(
    (experiment: Experiment) => {
      if (!projectId) return;
      router.push(
        `/experiments/${encodeURIComponent(experiment.id)}${projectQuery}`,
      );
    },
    [projectId, projectQuery, router],
  );

  if (
    liveQuery.isLoading ||
    datasetsQuery.isLoading ||
    experimentsQuery.isLoading ||
    evaluatorsQuery.isLoading
  ) {
    return <LoadingBlock className="min-h-[320px]" />;
  }

  if (
    liveQuery.isError ||
    datasetsQuery.isError ||
    experimentsQuery.isError ||
    evaluatorsQuery.isError
  ) {
    const err =
      liveQuery.error ??
      datasetsQuery.error ??
      experimentsQuery.error ??
      evaluatorsQuery.error;
    const message = formatErrorForUi(err);
    return (
      <ErrorState
        title="Could not load overview"
        message={message}
        onRetry={() => {
          void liveQuery.refetch();
          void datasetsQuery.refetch();
          void experimentsQuery.refetch();
          void evaluatorsQuery.refetch();
        }}
      />
    );
  }

  const liveRunsHref = projectId
    ? withProjectQuery("/live-runs", projectId)
    : "/live-runs";

  return (
    <div className="flex flex-col gap-6">
      <div className="sticky top-0 z-20 -mx-1 flex flex-wrap items-center justify-end gap-3 border-b border-border bg-background px-1 pb-3">
        {projectId ? (
          <RefreshControl
            dataUpdatedAt={dataUpdatedAt}
            onRefresh={onRefresh}
          />
        ) : null}
      </div>

      <PageIntro
        title="Overview"
        glossary="Where you are in the quality loop — what you already have vs what is missing."
      />

      {projectId ? <LoopProgress projectId={projectId} cards={loopCards} /> : null}

      {!hasCompletedExperiment ? (
        <p className="text-sm text-muted-foreground">
          Quality scores appear after you evaluate a run.{" "}
          <Link
            href={withProjectQuery("/experiments", projectId)}
            className="text-primary hover:underline"
          >
            Open runs
          </Link>
        </p>
      ) : null}

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-foreground">Live runs</h2>
        <div
          className="grid gap-2 sm:grid-cols-3"
          style={{ gap: "var(--grid-gap, 8px)" }}
        >
          <KpiStrip label="Total" value={liveTotal} href={liveRunsHref} />
          <KpiStrip label="Failed" value={liveFailed} href={liveRunsHref} />
          <KpiStrip
            label="In progress"
            value={livePending}
            href={liveRunsHref}
          />
        </div>
      </section>

      {liveTotal === 0 ? (
        <EmptyState
          title="No live runs yet"
          description="Live interactions scored by judges will show up here."
          action={
            <Link
              href={liveRunsHref}
              className="text-sm text-primary hover:underline"
            >
              Open live runs
            </Link>
          }
        />
      ) : null}

      <section className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold text-foreground">
            Recent live runs
          </h2>
          <Link
            href={`/live-runs${projectQuery}`}
            className="text-xs text-primary hover:underline"
          >
            View all
          </Link>
        </div>
        {recentLiveRuns.length === 0 ? (
          liveTotal === 0 ? null : (
            <p className="text-sm text-muted-foreground">No live runs yet.</p>
          )
        ) : (
          <DataTable
            rows={recentLiveRuns}
            columns={liveColumns}
            getRowKey={(row) => row.id}
            selectedIndex={liveSelectedIndex}
            onSelectedIndexChange={setLiveSelectedIndex}
            onRowActivate={onLiveActivate}
            aria-label="Recent live runs"
          />
        )}
      </section>

      <section className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold text-foreground">
            Latest runs
          </h2>
          <Link
            href={`/experiments${projectQuery}`}
            className="text-xs text-primary hover:underline"
          >
            View all
          </Link>
        </div>
        {latestExperiments.length === 0 ? (
          <p className="text-sm text-muted-foreground">No runs yet.</p>
        ) : (
          <DataTable
            rows={latestExperiments}
            columns={experimentColumns}
            getRowKey={(row) => row.id}
            selectedIndex={experimentSelectedIndex}
            onSelectedIndexChange={setExperimentSelectedIndex}
            onRowActivate={onExperimentActivate}
            aria-label="Latest runs"
          />
        )}
      </section>
    </div>
  );
}
