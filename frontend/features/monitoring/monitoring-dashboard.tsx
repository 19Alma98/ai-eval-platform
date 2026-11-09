"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { BellRing } from "lucide-react";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { ProductionHeader } from "@/components/production-header";
import { RefreshControl } from "@/components/refresh-control";
import { TimeRangePicker } from "@/components/time-range-picker";
import { buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OVERVIEW_DEFAULT_PRESET } from "@/features/overview/overview-range";
import { formatErrorForUi } from "@/lib/api/client";
import type { MetricMonitor, ProductionMonitoring } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDurationMs, formatPercent, formatScore, parseTimestamp } from "@/lib/format";
import { metricLabel } from "@/lib/metrics-catalog";
import { withProjectQuery } from "@/lib/project-href";
import {
  isPreset,
  parseTimeRangeParams,
  previousPeriod,
  rangeFromPreset,
  writeTimeRangeParams,
  type TimeWindow,
} from "@/lib/time-range";
import { useTimezone } from "@/lib/use-timezone";
import { tracesWindowHref } from "@/features/traces/attribute-filters";
import { alarmState, DEFAULT_ALARM_FAIL_RATE, metricKey, type AlarmThresholds } from "./alarms";
import { AnnotationQueue, annotationQueueQueryKey } from "./annotation-queue";
import { useAlarmThresholds } from "./use-alarm-thresholds";
import { ReleaseFilterControls, useReleaseFilter } from "./release-filter";
import { VersionsSection } from "./versions-section";
import {
  monitoringQueryKey,
  useMonitoring,
  useReleaseFacets,
  useVersionSummaries,
} from "./use-monitoring";
import { type ChartBucketClick } from "./monitoring-charts-inner";

const chartLoading = () => (
  <div className="h-[160px] animate-pulse rounded-md bg-surface-2" aria-hidden />
);
const LatencyChart = dynamic(
  () => import("./monitoring-charts-inner").then((m) => m.LatencyChartInner),
  { ssr: false, loading: chartLoading },
);
const TrafficChart = dynamic(
  () => import("./monitoring-charts-inner").then((m) => m.TrafficChartInner),
  { ssr: false, loading: chartLoading },
);
const UsageChart = dynamic(
  () => import("./monitoring-charts-inner").then((m) => m.UsageChartInner),
  { ssr: false, loading: chartLoading },
);
const MetricSeriesChart = dynamic(
  () => import("./monitoring-charts-inner").then((m) => m.MetricSeriesChartInner),
  { ssr: false, loading: chartLoading },
);
const HistogramChart = dynamic(
  () => import("./monitoring-charts-inner").then((m) => m.HistogramChartInner),
  { ssr: false, loading: chartLoading },
);

function Kpi({
  label,
  value,
  detail,
  tone,
  href,
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: "fail" | "warn";
  href?: string;
}) {
  const body = (
    <>
      <span className="text-xs text-muted-foreground">{label}</span>
      <span
        className={cn(
          "text-xl font-semibold tabular-nums text-foreground",
          tone === "fail" && "text-status-fail",
          tone === "warn" && "text-status-warn",
        )}
      >
        {value}
      </span>
      {detail ? <span className="text-xs text-muted-foreground">{detail}</span> : null}
    </>
  );
  const className = "flex flex-col gap-0.5 rounded-lg border border-border bg-surface px-4 py-3";
  return href ? (
    <Link href={href} className={cn(className, "hover:bg-row-hover")}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      {children}
    </section>
  );
}

function ms(value: number | null): string {
  return value != null ? formatDurationMs(value) : "—";
}

function MetricCard({
  metric,
  previous,
  thresholds,
  onAlarmChange,
  timeZone,
  onBucketClick,
}: {
  metric: MetricMonitor;
  previous?: MetricMonitor | null;
  thresholds: AlarmThresholds;
  onAlarmChange: (key: string, value: number | null) => void;
  timeZone: string;
  onBucketClick: (click: ChartBucketClick) => void;
}) {
  const alarm = alarmState(metric, thresholds);
  const key = metricKey(metric);
  const limitText = String(Math.round(alarm.limit * 100));
  const [draft, setDraft] = useState(limitText);
  const [syncedLimit, setSyncedLimit] = useState(limitText);
  if (syncedLimit !== limitText) {
    setSyncedLimit(limitText);
    setDraft(limitText);
  }
  const title = metric.source === "judge" ? metricLabel(metric.name) : metric.name;

  function commit() {
    if (draft.trim() === "") {
      setDraft(String(Math.round(DEFAULT_ALARM_FAIL_RATE * 100)));
      onAlarmChange(key, null);
      return;
    }
    const n = Number(draft);
    if (!Number.isFinite(n) || n < 0 || n > 100) {
      setDraft(limitText);
      return;
    }
    onAlarmChange(key, n / 100);
  }

  return (
    <section
      aria-label={`${title} metric`}
      className={cn(
        "flex flex-col gap-3 rounded-lg border bg-surface p-4",
        alarm.firing ? "border-status-fail" : "border-border",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <span className="rounded border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground">
          {metric.source === "judge" ? "LLM judge" : metric.source === "human" ? "User feedback" : "SDK"}
        </span>
        {alarm.firing ? (
          <span className="inline-flex items-center gap-1 rounded bg-status-fail-bg px-1.5 py-0.5 text-xs font-medium text-status-fail">
            <BellRing className="size-3" aria-hidden />
            Alarm
          </span>
        ) : null}
        <span className="flex-1" />
        <span className="text-xs text-muted-foreground">
          {metric.n} scored · mean {formatScore(metric.mean)} · failing{" "}
          {formatPercent(metric.fail_rate)}
          {metric.threshold != null ? ` · pass ≥ ${formatScore(metric.threshold)}` : ""}
        </span>
      </div>
      <div className="grid gap-4 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Mean and fail rate over time</span>
          <MetricSeriesChart
            metric={metric}
            previous={previous}
            alarmLimit={alarm.limit}
            timeZone={timeZone}
            onBucketClick={onBucketClick}
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Score distribution</span>
          {metric.histogram_counts.length > 0 ? (
            <HistogramChart metric={metric} />
          ) : (
            <p className="py-6 text-sm text-muted-foreground">No numeric scores.</p>
          )}
        </div>
      </div>
      <label className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        Alarm when more than
        <Input
          type="number"
          min={0}
          max={100}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
          }}
          className="h-7 w-16 text-xs"
          aria-label={`Alarm fail rate for ${title}`}
        />
        % of answers fail (window or latest bucket).
        {alarm.latestRate != null ? (
          <span>Latest bucket: {formatPercent(alarm.latestRate)}.</span>
        ) : null}
      </label>
    </section>
  );
}

function findPreviousMetric(
  metrics: MetricMonitor[] | undefined,
  metric: MetricMonitor,
): MetricMonitor | null {
  if (!metrics) return null;
  return metrics.find((m) => m.name === metric.name && m.source === metric.source) ?? null;
}

function Dashboard({
  projectId,
  data,
  previous,
  versions,
  timeZone,
  windowHref,
  onBucketClick,
}: {
  projectId: string;
  data: ProductionMonitoring;
  previous: ProductionMonitoring | null;
  versions: ReactNode;
  timeZone: string;
  windowHref: string;
  onBucketClick: (click: ChartBucketClick, opts?: { status?: "error" }) => void;
}) {
  const [thresholds, setAlarm] = useAlarmThresholds(projectId);
  const firing = data.metrics.filter((m) => alarmState(m, thresholds).firing);
  const errorRate = data.n_traces ? data.n_errors / data.n_traces : null;

  if (data.n_traces === 0 && data.metrics.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        <EmptyState
          title="No production traffic in this range"
          description="Once your app sends traces with the SDK, latency, cost and judge scores show up here over time. Experiment runs are not counted as production traffic."
          action={
            <>
              <Link
                href={withProjectQuery("/live-runs", projectId)}
                className={buttonVariants({ variant: "default", size: "sm" })}
              >
                Open live answers
              </Link>
              <Link href={windowHref} className={buttonVariants({ variant: "outline", size: "sm" })}>
                Browse all traces
              </Link>
            </>
          }
        />
        <div id="annotation-queue">
          <AnnotationQueue projectId={projectId} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {firing.length > 0 ? (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-2 rounded-md border border-status-fail bg-status-fail-bg px-3 py-2 text-sm text-status-fail"
        >
          <BellRing className="size-4" aria-hidden />
          <span>
            Alarm on {firing.map((m) => (m.source === "judge" ? metricLabel(m.name) : m.name)).join(", ")}:
            more answers fail than your alarm level.
          </span>
          <Link href={windowHref} className="font-medium underline underline-offset-2">
            View traces in this range
          </Link>
        </div>
      ) : null}
      {data.traces_truncated ? (
        <p className="rounded-md border border-status-warn bg-status-warn-bg px-3 py-2 text-sm text-status-warn">
          Too many traces in this range: latency, tokens and cost use the most recent ones only.
          Pick a shorter range for exact figures.
        </p>
      ) : null}

      <section aria-label="Production KPIs" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Kpi
          label="Traces"
          value={`${data.n_traces.toLocaleString()}${data.traces_truncated ? "+" : ""}`}
          detail={
            errorRate != null
              ? `${formatPercent(errorRate)} errors${data.traces_truncated ? " in the latest" : ""}`
              : undefined
          }
          tone={errorRate != null && errorRate > 0.05 ? "fail" : undefined}
          href={windowHref}
        />
        <Kpi
          label="Latency p50 / p90"
          value={ms(data.latency.p50_ms)}
          detail={`p90 ${ms(data.latency.p90_ms)} · p99 ${ms(data.latency.p99_ms)}`}
        />
        <Kpi
          label="Tokens"
          value={Math.round(data.total_tokens).toLocaleString()}
          detail={`${Math.round(data.prompt_tokens).toLocaleString()} in · ${Math.round(data.completion_tokens).toLocaleString()} out`}
        />
        <Kpi
          label="Cost"
          value={`$${data.cost_usd.toFixed(data.cost_usd < 1 ? 4 : 2)}`}
          detail={
            data.n_traces
              ? `$${(data.cost_usd / data.n_traces).toFixed(5)} per trace${data.traces_truncated ? " (latest traces)" : ""}`
              : undefined
          }
        />
        <Kpi
          label="Waiting for review"
          value={data.n_needs_review.toLocaleString()}
          detail="judged answers"
          tone={data.n_needs_review > 0 ? "warn" : undefined}
          href="#annotation-queue"
        />
      </section>

      {versions}

      <div className="grid gap-4 lg:grid-cols-3">
        <ChartCard title="Latency percentiles">
          <LatencyChart
            traffic={data.traffic}
            previous={previous?.traffic}
            timeZone={timeZone}
            onBucketClick={(c) => onBucketClick(c)}
          />
        </ChartCard>
        <ChartCard title="Traffic and errors">
          <TrafficChart
            traffic={data.traffic}
            previous={previous?.traffic}
            timeZone={timeZone}
            onBucketClick={(c) =>
              onBucketClick(c, {
                status: c.series === "errors" || c.series === "errors_prev" ? "error" : undefined,
              })
            }
          />
        </ChartCard>
        <ChartCard title="Tokens and cost">
          <UsageChart
            traffic={data.traffic}
            previous={previous?.traffic}
            timeZone={timeZone}
            onBucketClick={(c) => onBucketClick(c)}
          />
        </ChartCard>
      </div>

      <section aria-label="Quality metrics" className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-foreground">Quality metrics</h2>
        {data.metrics.length === 0 ? (
          <p className="rounded-md border border-dashed border-border bg-surface px-4 py-6 text-sm text-muted-foreground">
            No scores in this range. Live answers are scored by the judge; SDK metrics and user
            feedback logged with <code>opengrade.log_score()</code> show up here too.
          </p>
        ) : (
          data.metrics.map((metric) => (
            <MetricCard
              key={metricKey(metric)}
              metric={metric}
              previous={findPreviousMetric(previous?.metrics, metric)}
              thresholds={thresholds}
              onAlarmChange={setAlarm}
              timeZone={timeZone}
              onBucketClick={(c) => onBucketClick(c)}
            />
          ))
        )}
      </section>

      <div id="annotation-queue">
        <AnnotationQueue projectId={projectId} />
      </div>
    </div>
  );
}

export function MonitoringDashboard({ projectId }: { projectId: string }) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { timeZone, setTimeZone, options: timeZoneOptions } = useTimezone();
  const [anchor, setAnchor] = useState(() => new Date());
  const compare = searchParams.get("compare") === "1";

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
  const prev = useMemo(
    () => previousPeriod(window.start, window.end),
    [window.start, window.end],
  );

  const [release, setRelease] = useReleaseFilter();
  const query = useMonitoring(projectId, since, until, release);
  const previousQuery = useMonitoring(
    compare ? projectId : null,
    prev.start.toISOString(),
    prev.end.toISOString(),
    release,
  );
  const facets = useReleaseFacets(projectId, since, until);
  const showVersions = !release.version && (facets.data?.versions.length ?? 0) > 0;
  const versions = useVersionSummaries(
    projectId,
    since,
    until,
    release.environment ?? null,
    showVersions,
  );
  const queryClient = useQueryClient();

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

  const setCompare = useCallback(
    (on: boolean) => {
      const params = new URLSearchParams(searchParams.toString());
      if (on) params.set("compare", "1");
      else params.delete("compare");
      router.replace(`${pathname}?${params.toString()}`);
    },
    [pathname, router, searchParams],
  );

  const windowHref = useMemo(
    () =>
      tracesWindowHref({
        projectId,
        since,
        until,
        environment: release.environment,
        version: release.version,
      }),
    [projectId, since, until, release.environment, release.version],
  );

  const onBucketClick = useCallback(
    (click: ChartBucketClick, opts?: { status?: "error" }) => {
      const bucketSeconds = query.data?.bucket_seconds ?? 60;
      const start = parseTimestamp(click.bucketStart);
      const end = new Date(start.getTime() + bucketSeconds * 1000);
      router.push(
        tracesWindowHref({
          projectId,
          since: start.toISOString(),
          until: end.toISOString(),
          environment: release.environment,
          version: release.version,
          status: opts?.status ?? null,
        }),
      );
    },
    [projectId, query.data?.bucket_seconds, release.environment, release.version, router],
  );

  return (
    <div className="flex flex-col gap-4">
      <ProductionHeader
        active="health"
        actions={
          <>
            <ReleaseFilterControls facets={facets.data} filter={release} onChange={setRelease} />
            <TimeRangePicker
              window={window}
              onWindowChange={setWindow}
              showCustom
              showTimezone
              timeZone={timeZone}
              onTimeZoneChange={setTimeZone}
              timeZoneOptions={timeZoneOptions}
            />
            <label className="flex h-8 items-center gap-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={compare}
                onChange={(e) => setCompare(e.target.checked)}
                className="size-3.5 accent-primary"
              />
              Compare previous
            </label>
            <RefreshControl
              queryKey={monitoringQueryKey(projectId, since, until, release)}
              dataUpdatedAt={query.dataUpdatedAt}
              onRefresh={async () => {
                if (isPreset(window.kind)) setAnchor(new Date());
                await queryClient.invalidateQueries({
                  queryKey: annotationQueueQueryKey(projectId),
                });
              }}
            />
          </>
        }
      />
      {query.isLoading ? (
        <LoadingBlock className="min-h-[320px]" />
      ) : query.isError || !query.data ? (
        <ErrorState
          title="Could not load production metrics"
          message={formatErrorForUi(query.error)}
          onRetry={() => void query.refetch()}
        />
      ) : (
        <Dashboard
          key={projectId}
          projectId={projectId}
          data={query.data}
          previous={compare ? (previousQuery.data ?? null) : null}
          timeZone={timeZone}
          windowHref={windowHref}
          onBucketClick={onBucketClick}
          versions={
            showVersions && versions.data ? (
              <VersionsSection
                rows={versions.data}
                onSelect={(v) => setRelease("version", v)}
              />
            ) : null
          }
        />
      )}
    </div>
  );
}
