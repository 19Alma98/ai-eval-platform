"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { GitBranchPlus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { MetaItem, PageHeader } from "@/components/page-header";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, formatErrorForUi } from "@/lib/api/client";
import type { MetricsSetEntry, MetricsSetEntryInput } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import {
  METRIC_CATEGORY_LABELS,
  compareMetrics,
  metricCodeName,
  metricInfo,
  metricLabel,
  metricsSetDisplayName,
} from "@/lib/metrics-catalog";
import { withProjectQuery } from "@/lib/project-href";
import {
  metricsSetQueryOptions,
  useDeleteMetricsSetEntry,
  useMetricsSet,
  usePatchMetricsSet,
  useVersionMetricsSet,
} from "./use-metrics-sets";

type EntryRow = MetricsSetEntry;

/** Plain-language summary of the evaluator settings people actually tune. */
function settingsSummary(entry: MetricsSetEntry): string | null {
  const config = entry.config ?? {};
  const parts: string[] = [];
  if (typeof config.k === "number") parts.push(`top ${config.k} documents`);
  if (typeof config.max_ms === "number") {
    parts.push(`within ${(config.max_ms / 1000).toLocaleString()} s`);
  }
  if (typeof config.judge_model === "string") parts.push(`judge ${config.judge_model}`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

function entryToInput(entry: MetricsSetEntry): MetricsSetEntryInput {
  return {
    kind: entry.kind,
    enabled: entry.enabled,
    threshold: entry.threshold,
    config: entry.config,
    evaluator_id: entry.evaluator_id,
  };
}

export function MetricsSetDetailView({
  projectId,
  metricsSetId,
}: {
  projectId: string;
  metricsSetId: string;
}) {
  const router = useRouter();
  const query = useMetricsSet(metricsSetId);
  const patch = usePatchMetricsSet(metricsSetId, projectId);
  const version = useVersionMetricsSet(metricsSetId, projectId);
  const removeEntry = useDeleteMetricsSetEntry(metricsSetId, projectId);
  const queryOpts = metricsSetQueryOptions(metricsSetId);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [thresholdDraft, setThresholdDraft] = useState<Record<string, string>>(
    {},
  );
  const [versionLocked, setVersionLocked] = useState(false);

  const metricsSet = query.data;
  const rows: EntryRow[] = useMemo(
    () => [...(metricsSet?.entries ?? [])].sort((a, b) => compareMetrics(a.kind, b.kind)),
    [metricsSet?.entries],
  );

  const editsBlocked = versionLocked || patch.isPending;

  const saveEntries = useCallback(
    (nextEntries: MetricsSetEntry[]) => {
      patch.mutate(
        { entries: nextEntries.map(entryToInput) },
        {
          onError: (err) => {
            if (err instanceof ApiError && err.status === 409) {
              toast.error(
                "These metrics are already used by experiments. Create a new version to change them.",
              );
              setVersionLocked(true);
              return;
            }
            const message = formatErrorForUi(err);
            toast.error(message);
          },
        },
      );
    },
    [patch],
  );

  const toggleEnabled = useCallback(
    (row: EntryRow, enabled: boolean) => {
      if (!metricsSet || editsBlocked) return;
      const next = metricsSet.entries.map((entry) =>
        entry.id === row.id ? { ...entry, enabled } : entry,
      );
      saveEntries(next);
    },
    [metricsSet, editsBlocked, saveEntries],
  );

  const commitThreshold = useCallback(
    (row: EntryRow) => {
      if (!metricsSet || editsBlocked) return;
      const draft = thresholdDraft[row.id];
      const trimmed = draft?.trim() ?? "";
      let threshold: number | null = null;
      if (trimmed !== "") {
        const parsed = Number.parseFloat(trimmed);
        if (Number.isNaN(parsed)) {
          toast.error("The threshold must be a number");
          return;
        }
        threshold = parsed;
      }
      const current = row.threshold;
      if (current === threshold || (current == null && threshold == null)) {
        return;
      }
      const next = metricsSet.entries.map((entry) =>
        entry.id === row.id ? { ...entry, threshold } : entry,
      );
      saveEntries(next);
    },
    [metricsSet, editsBlocked, thresholdDraft, saveEntries],
  );

  const deleteEntry = useCallback(
    (row: EntryRow) => {
      if (!metricsSet || row.is_default || editsBlocked) return;
      removeEntry.mutate(row.id, {
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            toast.error(
              "These metrics are already used by experiments. Create a new version to change them.",
            );
            setVersionLocked(true);
            return;
          }
          const message = formatErrorForUi(err);
          toast.error(message);
        },
      });
    },
    [metricsSet, editsBlocked, removeEntry],
  );

  const nextVersionLabel =
    metricsSet != null ? `Create version ${metricsSet.version + 1}` : "Create new version";

  const columns: DataTableColumn<EntryRow>[] = useMemo(
    () => [
      {
        id: "enabled",
        header: "Active",
        headerClassName: "w-[72px]",
        cell: (row) => (
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={row.enabled}
            disabled={editsBlocked || removeEntry.isPending}
            aria-label={`Use ${metricLabel(row.kind)}`}
            onChange={(e) => toggleEnabled(row, e.target.checked)}
            onClick={(e) => e.stopPropagation()}
          />
        ),
      },
      {
        id: "kind",
        header: "Metric",
        wrap: true,
        cell: (row) => {
          const info = metricInfo(row.kind);
          return (
            <span className={cn("flex flex-col", !row.enabled && "opacity-60")}>
              <span className="font-medium text-foreground">
                {info.label}
                {metricCodeName(row.kind) ? (
                  <code className="ml-1.5 text-xs font-normal text-muted-foreground">
                    {row.kind}
                  </code>
                ) : null}
              </span>
              {info.description ? (
                <span className="text-xs text-muted-foreground">{info.description}</span>
              ) : null}
            </span>
          );
        },
      },
      {
        id: "category",
        header: "Measures",
        headerClassName: "w-[140px]",
        className: "text-sm text-muted-foreground",
        cell: (row) => METRIC_CATEGORY_LABELS[metricInfo(row.kind).category],
      },
      {
        id: "threshold",
        header: "Pass if score ≥",
        headerClassName: "w-[140px]",
        cell: (row) =>
          row.threshold == null && !(row.id in thresholdDraft) && settingsSummary(row) ? (
            <span className="text-sm text-muted-foreground">Pass / fail</span>
          ) : (
            <Input
              type="number"
              step="0.05"
              min={0}
              max={1}
              className="h-8 w-24 tabular-nums"
              placeholder="—"
              value={
                thresholdDraft[row.id] ??
                (row.threshold == null ? "" : String(row.threshold))
              }
              disabled={editsBlocked || removeEntry.isPending}
              aria-label={`Pass threshold for ${metricLabel(row.kind)}`}
              onChange={(e) => {
                setThresholdDraft((prev) => ({
                  ...prev,
                  [row.id]: e.target.value,
                }));
              }}
              onBlur={() => commitThreshold(row)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  commitThreshold(row);
                }
              }}
              onClick={(e) => e.stopPropagation()}
            />
          ),
      },
      {
        id: "settings",
        header: "Settings",
        headerClassName: "w-[180px]",
        className: "text-sm text-muted-foreground",
        cell: (row) => settingsSummary(row) ?? "—",
      },
      {
        id: "actions",
        header: "",
        headerClassName: "w-[52px]",
        cell: (row) =>
          row.is_default ? null : (
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              disabled={editsBlocked || removeEntry.isPending}
              aria-label={`Remove ${metricLabel(row.kind)}`}
              onClick={(e) => {
                e.stopPropagation();
                deleteEntry(row);
              }}
            >
              <Trash2 className="size-4 text-muted-foreground" />
            </Button>
          ),
      },
    ],
    [
      thresholdDraft,
      editsBlocked,
      removeEntry.isPending,
      commitThreshold,
      deleteEntry,
      toggleEnabled,
    ],
  );

  if (query.isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (query.isError) {
    const err = query.error;
    const message = formatErrorForUi(err);
    return (
      <ErrorState
        title="Could not load metrics"
        message={message}
        onRetry={() => query.refetch()}
      />
    );
  }

  if (!metricsSet) {
    return null;
  }

  const listHref = withProjectQuery("/metrics", projectId);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        breadcrumbs={[
          { label: "Metrics", href: listHref },
          { label: metricsSetDisplayName(metricsSet.name) },
        ]}
        title={metricsSetDisplayName(metricsSet.name)}
        badges={
          <>
            <Badge variant="outline">v{metricsSet.version}</Badge>
            {metricsSet.is_project_default ? (
              <Badge variant="secondary">Project default</Badge>
            ) : null}
          </>
        }
        description={
          metricsSet.description ||
          "Each answer is scored from 0 to 1 on every active metric and passes when it reaches the threshold."
        }
        meta={
          <>
            <MetaItem label="Active">
              {metricsSet.enabled_count} of {metricsSet.entry_count} metrics
            </MetaItem>
            <MetaItem label="Updated">
              <RelativeTime date={metricsSet.updated_at} />
            </MetaItem>
          </>
        }
        actions={
          <>
            <RefreshControl
              queryKey={queryOpts.queryKey}
              dataUpdatedAt={query.dataUpdatedAt}
            />
            <Button
              type="button"
              size="sm"
              variant={versionLocked ? "default" : "outline"}
              disabled={version.isPending}
              title="Copy these metrics into a new version you can edit, without changing past experiments"
              onClick={() => {
                version.mutate(undefined, {
                  onSuccess: (created) => {
                    toast.success("New version created");
                    router.push(
                      `/metrics/${encodeURIComponent(created.id)}?project=${encodeURIComponent(projectId)}`,
                    );
                  },
                  onError: (err) => {
                    toast.error(formatErrorForUi(err));
                  },
                });
              }}
            >
              <GitBranchPlus className="size-4" />
              {version.isPending ? "Creating…" : nextVersionLabel}
            </Button>
          </>
        }
        className="mb-0"
      />

      {versionLocked ? (
        <p className="rounded-md border border-status-warn bg-status-warn-bg px-3 py-2 text-sm text-foreground">
          Experiments were already scored with these metrics, so they are locked to
          keep past results comparable. Use “{nextVersionLabel}” to make changes.
        </p>
      ) : null}

      {rows.length === 0 ? (
        <EmptyState
          title="No metrics in this set"
          description="This metrics set does not contain any metric."
        />
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          getRowKey={(row) => row.id}
          selectedIndex={selectedIndex}
          onSelectedIndexChange={setSelectedIndex}
          onRowActivate={() => {}}
          aria-label="Metrics in this set"
        />
      )}
    </div>
  );
}
