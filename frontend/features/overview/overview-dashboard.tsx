"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { PageIntro } from "@/components/page-intro";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { formatErrorForUi } from "@/lib/api/client";
import type { Experiment, TraceSummary } from "@/lib/api/types";
import { formatDurationMs } from "@/lib/format";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { useTimeRange } from "@/lib/time-range-context";
import { cn } from "@/lib/cn";
import {
  evaluatorsQueryKey,
  experimentsQueryKey,
  experimentsQueryOptions,
  useEvaluators,
  useExperiments,
} from "@/features/experiments/use-experiments";
import {
  datasetsQueryKey,
  datasetsQueryOptions,
  useDatasets,
} from "@/features/datasets/use-datasets";
import {
  tracesQueryKey,
  tracesQueryOptions,
  useTraces,
} from "@/features/traces/use-traces";
import { LoopProgress } from "@/features/overview/loop-progress";

function traceDurationMs(trace: TraceSummary): number | null {
  if (!trace.end_time) return null;
  return (
    new Date(trace.end_time).getTime() - new Date(trace.start_time).getTime()
  );
}

function isErroredTrace(trace: TraceSummary): boolean {
  const s = trace.status.toLowerCase();
  return s === "error" || s === "fail" || s === "failed";
}

function percentile(values: number[], p: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.ceil(p * sorted.length) - 1;
  return sorted[Math.max(0, idx)];
}

type SparkPoint = { i: number; v: number };

function MiniSparkline({
  data,
  colorVar,
  ariaLabel,
}: {
  data: SparkPoint[];
  colorVar: string;
  ariaLabel: string;
}) {
  if (data.length < 5) return null;
  return (
    <div className="mt-2 h-8 w-full" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
          <Area
            type="monotone"
            dataKey="v"
            stroke={`hsl(var(${colorVar}))`}
            fill={`hsl(var(${colorVar}) / 0.15)`}
            strokeWidth={1.5}
            isAnimationActive={false}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function KpiStrip({
  label,
  value,
  href,
  subLink,
  sparkline,
  className,
}: {
  label: string;
  value: React.ReactNode;
  href?: string;
  subLink?: { label: string; href: string };
  sparkline?: React.ReactNode;
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
      {sparkline}
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
  const { start, end } = useTimeRange();

  const traceFilters = useMemo(
    () => ({
      start: start.toISOString(),
      end: end.toISOString(),
      limit: 100,
    }),
    [start, end],
  );

  const [traceSelectedIndex, setTraceSelectedIndex] = useState(0);
  const [experimentSelectedIndex, setExperimentSelectedIndex] = useState(0);

  const tracesQuery = useTraces(projectId, traceFilters);
  const datasetsQuery = useDatasets(projectId);
  const experimentsQuery = useExperiments(projectId);
  const evaluatorsQuery = useEvaluators(projectId);

  const traceOpts = projectId
    ? tracesQueryOptions(projectId, traceFilters)
    : null;
  const datasetsOpts = projectId ? datasetsQueryOptions(projectId) : null;
  const expOpts = projectId ? experimentsQueryOptions(projectId) : null;

  const traces = tracesQuery.data?.items ?? [];
  const datasets = datasetsQuery.data ?? [];
  const experiments = experimentsQuery.data ?? [];

  const projectQuery = projectId ? `?project=${encodeURIComponent(projectId)}` : "";

  const metrics = useMemo(() => {
    const sorted = [...traces].sort(
      (a, b) =>
        new Date(a.start_time).getTime() - new Date(b.start_time).getTime(),
    );
    const total = sorted.length;
    const errored = sorted.filter(isErroredTrace).length;
    const errorRate = total > 0 ? errored / total : null;

    const durations = sorted
      .map(traceDurationMs)
      .filter((ms): ms is number => ms != null);
    const latencyP95 = percentile(durations, 0.95);

    let rollingErrors = 0;
    const errorSpark: SparkPoint[] = sorted.map((t, i) => {
      if (isErroredTrace(t)) rollingErrors += 1;
      return { i, v: total > 0 ? (rollingErrors / (i + 1)) * 100 : 0 };
    });

    const latencySpark: SparkPoint[] = sorted
      .map((t, i) => ({ t, i }))
      .filter(({ t }) => traceDurationMs(t) != null)
      .map(({ t, i }) => ({ i, v: traceDurationMs(t)! }));

    return {
      errorRate,
      latencyP95,
      errorSpark,
      latencySpark,
      total,
    };
  }, [traces]);

  const recentTraces = useMemo(
    () =>
      [...traces]
        .sort(
          (a, b) =>
            new Date(b.start_time).getTime() - new Date(a.start_time).getTime(),
        )
        .slice(0, 10),
    [traces],
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
    tracesQuery.dataUpdatedAt ?? 0,
    datasetsQuery.dataUpdatedAt ?? 0,
    experimentsQuery.dataUpdatedAt ?? 0,
    evaluatorsQuery.dataUpdatedAt ?? 0,
  );

  const onRefresh = useCallback(async () => {
    if (!projectId) return;
    await Promise.all([
      queryClient.refetchQueries({
        queryKey: tracesQueryKey(projectId, traceFilters),
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
  }, [projectId, queryClient, traceFilters]);

  const traceColumns: DataTableColumn<TraceSummary>[] = useMemo(
    () => [
      {
        id: "time",
        header: "Time",
        headerClassName: "w-[100px]",
        cell: (row) => <RelativeTime date={row.start_time} />,
      },
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
        headerClassName: "w-[88px]",
        cell: (row) => <StatusBadge status={row.status} />,
      },
      {
        id: "duration",
        header: "Duration",
        headerClassName: "w-[88px]",
        className: "font-mono tabular-nums text-muted-foreground",
        cell: (row) => {
          const ms = traceDurationMs(row);
          return ms == null ? "—" : formatDurationMs(ms);
        },
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

  const onTraceActivate = useCallback(
    (trace: TraceSummary) => {
      if (!projectId) return;
      router.push(
        `/traces/${encodeURIComponent(trace.trace_id)}${projectQuery}`,
      );
    },
    [projectId, projectQuery, router],
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
    tracesQuery.isLoading ||
    datasetsQuery.isLoading ||
    experimentsQuery.isLoading ||
    evaluatorsQuery.isLoading
  ) {
    return <LoadingBlock className="min-h-[320px]" />;
  }

  if (
    tracesQuery.isError ||
    datasetsQuery.isError ||
    experimentsQuery.isError ||
    evaluatorsQuery.isError
  ) {
    const err =
      tracesQuery.error ??
      datasetsQuery.error ??
      experimentsQuery.error ??
      evaluatorsQuery.error;
    const message = formatErrorForUi(err);
    return (
      <ErrorState
        title="Could not load overview"
        message={message}
        onRetry={() => {
          void tracesQuery.refetch();
          void datasetsQuery.refetch();
          void experimentsQuery.refetch();
          void evaluatorsQuery.refetch();
        }}
      />
    );
  }

  const errorRateDisplay =
    metrics.errorRate != null
      ? `${(metrics.errorRate * 100).toFixed(1)}%`
      : "—";

  const latencyDisplay =
    metrics.latencyP95 != null
      ? formatDurationMs(metrics.latencyP95)
      : "—";

  const errorTracesHref = projectId
    ? withProjectQuery("/traces?status=error", projectId)
    : "/traces?status=error";

  return (
    <div className="flex flex-col gap-6">
      <div className="sticky top-0 z-20 -mx-1 flex flex-wrap items-center justify-end gap-3 border-b border-border bg-background px-1 pb-3">
        {traceOpts && datasetsOpts && expOpts ? (
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
        <h2 className="text-sm font-semibold text-foreground">
          From traces (telemetry)
        </h2>
        <div
          className="grid gap-2 sm:grid-cols-2"
          style={{ gap: "var(--grid-gap, 8px)" }}
        >
          <KpiStrip
            label="Error rate"
            value={errorRateDisplay}
            href={errorTracesHref}
            sparkline={
              <MiniSparkline
                data={metrics.errorSpark}
                colorVar="--chart-3"
                ariaLabel="Error rate trend from recent traces"
              />
            }
          />
          <KpiStrip
            label="Latency (p95)"
            value={latencyDisplay}
            href={withProjectQuery("/traces", projectId)}
            sparkline={
              <MiniSparkline
                data={metrics.latencySpark}
                colorVar="--chart-1"
                ariaLabel="Latency trend from recent traces"
              />
            }
          />
        </div>
      </section>

      {metrics.total === 0 ? (
        <EmptyState
          title="No traces yet"
          description="No traces yet. Run the OTLP example or `docker compose` demo."
        />
      ) : null}

      <section className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold text-foreground">
            Recent traces
          </h2>
          <Link
            href={`/traces${projectQuery}`}
            className="text-xs text-primary hover:underline"
          >
            View all
          </Link>
        </div>
        {recentTraces.length === 0 ? (
          <p className="text-sm text-muted-foreground">No traces in window.</p>
        ) : (
          <DataTable
            rows={recentTraces}
            columns={traceColumns}
            getRowKey={(row) => row.trace_id}
            selectedIndex={traceSelectedIndex}
            onSelectedIndexChange={setTraceSelectedIndex}
            onRowActivate={onTraceActivate}
            aria-label="Recent traces"
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
