"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { TimeRangePicker } from "@/components/time-range-picker";
import { RefreshControl } from "@/components/refresh-control";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { formatErrorForUi } from "@/lib/api/client";
import { getMonitoring } from "@/lib/api/monitoring";
import { getOverview } from "@/lib/api/overview";
import { getTraceScoreSummary } from "@/lib/api/trace-scores";
import { useProjectId } from "@/lib/project-store";
import { rangeFromPreset, type Preset } from "@/lib/time-range";
import { cn } from "@/lib/cn";
import { useAlarmThresholds } from "@/features/monitoring/use-alarm-thresholds";
import { monitoringQueryKey, useMonitoring } from "@/features/monitoring/use-monitoring";
import { parseOverviewRangeParam, OVERVIEW_DEFAULT_PRESET } from "./overview-range";
import { useOverview, overviewQueryKey } from "./use-overview";
import { LiveQualityChart } from "./live-quality-chart";
import { CompareBars } from "./compare-bars";
import { AttentionQueue } from "./attention-queue";
import { LoopProgress } from "./loop-progress";
import { ProductionScoresCard } from "./production-scores-card";
import { StatusPanels } from "./status-panels";
import { traceScoreSummaryQueryKey } from "./use-trace-score-summary";
import {
  buildLivePanel,
  buildLoopCards,
  buildReleasePanel,
  mergeAttentionItems,
  overviewWarningMessages,
} from "./map-overview";

function OverviewSkeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-md border border-border bg-surface-2", className)}
      aria-hidden
    />
  );
}

export function OverviewDashboard() {
  const { projectId } = useProjectId();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();

  const preset = parseOverviewRangeParam(searchParams.get("range"));
  // Window end is anchored in state so Refresh / preset changes move it forward
  // instead of refetching the window computed at page load.
  const [anchor, setAnchor] = useState(() => new Date());
  const { start, end } = useMemo(() => rangeFromPreset(preset, anchor), [preset, anchor]);
  const since = start.toISOString();
  const until = end.toISOString();
  const overviewQuery = useOverview(projectId, since, until);
  const monitoringQuery = useMonitoring(projectId, since, until);
  const [alarmThresholds] = useAlarmThresholds(projectId ?? "");

  useEffect(() => {
    if (searchParams.get("range") != null) return;
    const params = new URLSearchParams(searchParams.toString());
    params.set("range", OVERVIEW_DEFAULT_PRESET);
    router.replace(`${pathname}?${params.toString()}`);
  }, [pathname, router, searchParams]);

  const setPreset = useCallback(
    (p: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("range", p);
      setAnchor(new Date());
      router.replace(`${pathname}?${params.toString()}`);
    },
    [pathname, router, searchParams],
  );

  const widenRange = useCallback(() => {
    const order: Preset[] = ["15m", "1h", "6h", "24h", "7d"];
    const idx = order.indexOf(preset);
    const next = order[Math.min(idx + 1, order.length - 1)];
    setPreset(next);
  }, [preset, setPreset]);

  const onRefresh = useCallback(async () => {
    if (!projectId) return;
    // New anchor → new query keys → the overview, production scores and
    // monitoring queries all fetch the window ending now.
    const next = rangeFromPreset(preset, new Date());
    const nextSince = next.start.toISOString();
    const nextUntil = next.end.toISOString();
    setAnchor(next.end);
    await Promise.all([
      queryClient.fetchQuery({
        queryKey: overviewQueryKey(projectId, nextSince, nextUntil),
        queryFn: () => getOverview(projectId, nextSince, nextUntil),
      }),
      queryClient.fetchQuery({
        queryKey: traceScoreSummaryQueryKey(projectId, nextSince, nextUntil),
        queryFn: () => getTraceScoreSummary(projectId, nextSince, nextUntil),
      }),
      queryClient.fetchQuery({
        queryKey: monitoringQueryKey(projectId, nextSince, nextUntil),
        queryFn: () => getMonitoring(projectId, nextSince, nextUntil),
      }),
    ]).catch(() => undefined); // errors surface through the queries themselves
  }, [preset, projectId, queryClient]);

  const overview = overviewQuery.data;
  const loading = overviewQuery.isLoading && !overview;
  const loadFailed = overviewQuery.isError && !overview;

  const releasePanel = overview ? buildReleasePanel(overview) : null;
  const livePanel = overview ? buildLivePanel(overview, preset) : null;
  const loopCards = overview ? buildLoopCards(overview) : null;
  const attentionRows = overview
    ? mergeAttentionItems(overview, {
        metrics: monitoringQuery.data?.metrics,
        alarmThresholds,
      })
    : [];
  const warningMessages = overview ? overviewWarningMessages(overview.warnings) : [];

  const setupIncomplete = loopCards?.some((c) => c.status === "empty") ?? false;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Overview"
        description="Is the next version safe to ship, and is production healthy right now?"
        actions={
          <>
            <TimeRangePicker preset={preset} onPresetChange={setPreset} />
            {projectId ? (
              <RefreshControl
                dataUpdatedAt={overviewQuery.dataUpdatedAt}
                onRefresh={onRefresh}
              />
            ) : null}
          </>
        }
        className="mb-0"
      />

      {warningMessages.length > 0 ? (
        <div
          role="status"
          className="rounded-md border border-status-warn bg-status-warn-bg px-3 py-2 text-sm text-status-warn"
        >
          {warningMessages.map((message) => (
            <p key={message}>{message}</p>
          ))}
        </div>
      ) : null}

      {loadFailed ? (
        <ErrorState
          title="Could not load overview"
          message={formatErrorForUi(overviewQuery.error)}
          onRetry={() => void overviewQuery.refetch()}
        />
      ) : null}

      <div
        aria-busy={loading}
        className={cn("flex flex-col gap-6", loading && "pointer-events-none opacity-90")}
      >
        {loadFailed ? null : loading || !projectId || !releasePanel || !livePanel ? (
          <>
            <div className="grid gap-4 lg:grid-cols-2">
              <OverviewSkeleton className="h-56" />
              <OverviewSkeleton className="h-56" />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <OverviewSkeleton className="h-64" />
              <OverviewSkeleton className="h-64" />
            </div>
          </>
        ) : overview ? (
          <>
            {setupIncomplete && loopCards ? (
              <section className="flex flex-col gap-2">
                <h2 className="text-sm font-semibold text-foreground">Getting started</h2>
                <LoopProgress projectId={projectId} cards={loopCards} />
              </section>
            ) : null}

            <StatusPanels
              projectId={projectId}
              release={overview.offline.latest_experiment ? releasePanel : null}
              live={livePanel}
            />

            <div className="grid gap-4 lg:grid-cols-2">
              <AttentionQueue projectId={projectId} rows={attentionRows} />
              <CompareBars projectId={projectId} overview={overview} />
            </div>

            {overview.live.n_interactions > 0 ? (
              <LiveQualityChart
                projectId={projectId}
                series={overview.live.series}
                referenceThreshold={overview.offline.reference_threshold}
                onWidenRange={widenRange}
              />
            ) : null}

            <ProductionScoresCard projectId={projectId} since={since} until={until} />
          </>
        ) : null}
      </div>
    </div>
  );
}
