"use client";

import { useMemo, useState } from "react";
import { PackagePlus } from "lucide-react";
import { toast } from "sonner";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";
import type { MetricsPackEntry } from "@/lib/api/types";
import {
  metricsPackQueryOptions,
  useEnsureMetricsPack,
  useMetricsPack,
  useUpdateMetricsPack,
} from "./use-metrics-pack";

type EntryRow = MetricsPackEntry & { id: string };

function kindLabel(kind: string): string {
  return kind.replace(/_/g, " ");
}

export function MetricsPackPage({ projectId }: { projectId: string }) {
  const query = useMetricsPack(projectId);
  const ensure = useEnsureMetricsPack(projectId);
  const update = useUpdateMetricsPack(projectId);
  const queryOpts = metricsPackQueryOptions(projectId);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [thresholdDraft, setThresholdDraft] = useState<
    Record<string, string>
  >({});

  const pack = query.data;
  const rows: EntryRow[] = useMemo(
    () =>
      (pack?.entries ?? []).map((entry) => ({
        ...entry,
        id: entry.kind,
      })),
    [pack?.entries],
  );

  function entryPayload(entry: MetricsPackEntry): MetricsPackEntry {
    return {
      kind: entry.kind,
      enabled: entry.enabled,
      threshold: entry.threshold,
      config: entry.config,
      evaluator_id: entry.evaluator_id,
      removable: entry.removable,
    };
  }

  function saveEntries(nextEntries: MetricsPackEntry[]) {
    update.mutate(nextEntries.map(entryPayload), {
      onError: (err) => {
        const message =
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Update failed";
        toast.error(message);
      },
    });
  }

  function toggleEnabled(row: EntryRow, enabled: boolean) {
    if (!pack) return;
    const next = pack.entries.map((entry) =>
      entry.kind === row.kind ? { ...entry, enabled } : entry,
    );
    saveEntries(next);
  }

  function commitThreshold(row: EntryRow) {
    if (!pack) return;
    const draft = thresholdDraft[row.kind];
    const trimmed = draft?.trim() ?? "";
    let threshold: number | null = null;
    if (trimmed !== "") {
      const parsed = Number.parseFloat(trimmed);
      if (Number.isNaN(parsed)) {
        toast.error("Threshold must be a number");
        return;
      }
      threshold = parsed;
    }
    const current = row.threshold;
    if (current === threshold || (current == null && threshold == null)) {
      return;
    }
    const next = pack.entries.map((entry) =>
      entry.kind === row.kind ? { ...entry, threshold } : entry,
    );
    saveEntries(next);
  }

  const columns: DataTableColumn<EntryRow>[] = useMemo(
    () => [
      {
        id: "kind",
        header: "Metric",
        headerClassName: "w-[160px]",
        cell: (row) => (
          <Badge variant="secondary" className="font-mono text-xs">
            {kindLabel(row.kind)}
          </Badge>
        ),
      },
      {
        id: "enabled",
        header: "Enabled",
        headerClassName: "w-[88px]",
        cell: (row) => (
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={row.enabled}
            disabled={update.isPending}
            aria-label={`Enable ${row.kind}`}
            onChange={(e) => toggleEnabled(row, e.target.checked)}
            onClick={(e) => e.stopPropagation()}
          />
        ),
      },
      {
        id: "threshold",
        header: "Threshold",
        headerClassName: "w-[140px]",
        cell: (row) => (
          <Input
            type="number"
            step="any"
            className="h-8 font-mono text-xs"
            placeholder="—"
            value={
              thresholdDraft[row.kind] ??
              (row.threshold == null ? "" : String(row.threshold))
            }
            disabled={update.isPending}
            onChange={(e) => {
              setThresholdDraft((prev) => ({
                ...prev,
                [row.kind]: e.target.value,
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
        id: "evaluator",
        header: "Evaluator",
        cell: (row) => (
          <span className="font-mono text-xs text-muted-foreground">
            {row.evaluator_id ?? "—"}
          </span>
        ),
      },
    ],
    [thresholdDraft, update.isPending, pack],
  );

  if (query.isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (query.isError) {
    const err = query.error;
    if (err instanceof ApiError && err.status === 404) {
      return (
        <EmptyState
          title="No metrics pack yet"
          description="Create the default RAG evaluator pack for this project (hit@k, groundedness, correctness, latency)."
          action={
            <Button
              type="button"
              size="sm"
              disabled={ensure.isPending}
              onClick={() => {
                ensure.mutate(undefined, {
                  onSuccess: () => toast.success("Metrics pack ready"),
                  onError: (e) => {
                    const message =
                      e instanceof ApiError
                        ? e.message
                        : e instanceof Error
                          ? e.message
                          : "Could not create pack";
                    toast.error(message);
                  },
                });
              }}
            >
              <PackagePlus className="size-4" />
              {ensure.isPending ? "Creating…" : "Ensure pack"}
            </Button>
          }
        />
      );
    }
    const message =
      err instanceof ApiError
        ? `${err.status}: ${err.message}`
        : err instanceof Error
          ? err.message
          : "Unknown error";
    return (
      <ErrorState
        title="Could not load metrics pack"
        message={message}
        onRetry={() => query.refetch()}
      />
    );
  }

  if (!pack) {
    return null;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Updated <RelativeTime date={pack.updated_at} /> ·{" "}
          <span className="font-mono tabular-nums text-foreground">
            {pack.entries.length}
          </span>{" "}
          metrics
        </p>
        <RefreshControl
          queryKey={queryOpts.queryKey}
          dataUpdatedAt={query.dataUpdatedAt}
        />
      </div>
      {rows.length === 0 ? (
        <EmptyState
          title="Empty pack"
          description="The metrics pack has no entries."
        />
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          getRowKey={(row) => row.id}
          selectedIndex={selectedIndex}
          onSelectedIndexChange={setSelectedIndex}
          onRowActivate={() => {}}
          aria-label="Metrics pack entries"
        />
      )}
    </div>
  );
}
