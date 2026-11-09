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
import {
  isPreset,
  parseTimeRangeParams,
  rangeFromPreset,
  writeTimeRangeParams,
  type Preset,
  type TimeWindow,
} from "@/lib/time-range";
import { useTimezone } from "@/lib/use-timezone";
import { cn } from "@/lib/cn";
import { useAlarmThresholds } from "@/features/monitoring/use-alarm-thresholds";
import { monitoringQueryKey, useMonitoring } from "@/features/monitoring/use-monitoring";
import { OVERVIEW_DEFAULT_PRESET } from "./overview-range";
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
  const { timeZone, setTimeZone, options: timeZoneOptions } = useTimezone();

  // Window end is anchored in state so Refresh / preset changes move it forward
  // instead of refetching the window computed at page load.
  const [anchor, setAnchor] = useState(() => new Date());
  const window = useMemo(
    () =>
      parseTimeRangeParams(searchParams, {
        defaultPreset: OVERVIEW_DEFAULT_PRESET,
        anchor,
      }),
    [searchParams, anchor],
  );
  const since = window.start.toISOString();
  const until = window.end.toISOString();
  const overviewQuery = useOverview(projectId, since, until);
  const monitoringQuery = useMonitoring(projectId, since, until);
  const [alarmThresholds] = useAlarmThresholds(projectId ?? "");

  useEffect(() => {
    if (searchParams.get("range") != null) return;
    const params = new URLSearchParams(searchParams.toString());
    writeTimeRangeParams(params, rangeFromPreset(OVERVIEW_DEFAULT_PRESET, anchor));
    router.replace(`${pathname}?${params.toString()}`);
  }, [anchor, pathname, router, searchParams]);

  const setWindow = useCallback(
    (next: TimeWindow) => {
      const params = new URLSearchParams(searchParams.toString());
      if (isPreset(next.kind)) {
        const fresh = rangeFromPreset(next.kind, new Date());
        setAnchor(fresh.end);
        writeTimeRangeParams(params, fresh);
      } else {
        writeTimeRangeParams(params, next);
      }
      router.replace(`${pathname}?${params.toString()}`);
    },
    [pathname, router, searchParams],
  );

  const widenRange = useCallback(() => {
    const order: Preset[] = ["15m", "1h", "6h", "24h", "7d"];
    const kind = isPreset(window.kind) ? window.kind : OVERVIEW_DEFAULT_PRESET;
    const idx = order.indexOf(kind);
    const next = order[Math.min(idx + 1, order.length - 1)];
    setWindow(rangeFromPreset(next, new Date()));
  }, [window.kind, setWindow]);

  const onRefresh = useCallback(async () => {
    if (!projectId) return;
    let nextSince = since;
    let nextUntil = until;
    if (isPreset(window.kind)) {
      const next = rangeFromPreset(window.kind, new Date());
      nextSince = next.start.toISOString();
      nextUntil = next.end.toISOString();
      setAnchor(next.end);
    }
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
  }, [projectId, queryClient, since, until, window.kind]);

  const overview = overviewQuery.data;
  const loading = overviewQuery.isLoading && !overview;
  const loadFailed = overviewQuery.isError && !overview;

  const releasePanel = overview ? buildReleasePanel(overview) : null;
  const livePanel = overview
    ? buildLivePanel(overview, isPreset(window.kind) ? window.kind : "custom")
    : null;
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
            <TimeRangePicker
              window={window}
              onWindowChange={setWindow}
              showCustom
              showTimezone
              timeZone={timeZone}
              onTimeZoneChange={setTimeZone}
              timeZoneOptions={timeZoneOptions}
            />
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
        className={cn("flex flex-col gap-10", loading && "pointer-events-none opacity-90")}
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
                <h2 className="font-serif text-lg font-medium text-foreground">Getting started</h2>
                <LoopProgress projectId={projectId} cards={loopCards} />
              </section>
            ) : null}

            <StatusPanels
              projectId={projectId}
              release={overview.offline.latest_experiment ? releasePanel : null}
              live={livePanel}
            />

            <div className="grid gap-x-12 gap-y-10 lg:grid-cols-2">
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
