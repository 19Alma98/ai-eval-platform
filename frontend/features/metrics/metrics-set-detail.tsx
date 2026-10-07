"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { ArrowLeft, GitBranchPlus, Trash2 } from "lucide-react";
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
import type { MetricsSetEntry, MetricsSetEntryInput } from "@/lib/api/types";
import { resolveLabel } from "@/lib/format";
import { withProjectQuery } from "@/lib/project-href";
import { useEvaluators } from "@/features/experiments/use-experiments";
import {
  metricsSetQueryOptions,
  useDeleteMetricsSetEntry,
  useMetricsSet,
  usePatchMetricsSet,
  useVersionMetricsSet,
} from "./use-metrics-sets";

type EntryRow = MetricsSetEntry;

function kindLabel(kind: string): string {
  return kind.replace(/_/g, " ");
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
  const evaluatorsQuery = useEvaluators(projectId);
  const queryOpts = metricsSetQueryOptions(metricsSetId);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [thresholdDraft, setThresholdDraft] = useState<Record<string, string>>(
    {},
  );
  const [versionLocked, setVersionLocked] = useState(false);

  const metricsSet = query.data;
  const rows: EntryRow[] = useMemo(
    () => metricsSet?.entries ?? [],
    [metricsSet?.entries],
  );

  const evaluatorNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const ev of evaluatorsQuery.data ?? []) {
      map.set(ev.id, ev.name);
    }
    return map;
  }, [evaluatorsQuery.data]);

  const editsBlocked = versionLocked || patch.isPending;

  function saveEntries(nextEntries: MetricsSetEntry[]) {
    patch.mutate(
      { entries: nextEntries.map(entryToInput) },
      {
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            toast.error(
              "Set in uso: crea una nuova versione per modificare le voci.",
            );
            setVersionLocked(true);
            return;
          }
          const message =
            err instanceof ApiError
              ? err.message
              : err instanceof Error
                ? err.message
                : "Aggiornamento fallito";
          toast.error(message);
        },
      },
    );
  }

  function toggleEnabled(row: EntryRow, enabled: boolean) {
    if (!metricsSet || editsBlocked) return;
    const next = metricsSet.entries.map((entry) =>
      entry.id === row.id ? { ...entry, enabled } : entry,
    );
    saveEntries(next);
  }

  function commitThreshold(row: EntryRow) {
    if (!metricsSet || editsBlocked) return;
    const draft = thresholdDraft[row.id];
    const trimmed = draft?.trim() ?? "";
    let threshold: number | null = null;
    if (trimmed !== "") {
      const parsed = Number.parseFloat(trimmed);
      if (Number.isNaN(parsed)) {
        toast.error("La soglia deve essere un numero");
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
  }

  function deleteEntry(row: EntryRow) {
    if (!metricsSet || row.is_default || editsBlocked) return;
    removeEntry.mutate(row.id, {
      onError: (err) => {
        if (err instanceof ApiError && err.status === 409) {
          toast.error(
            "Set in uso: crea una nuova versione per modificare le voci.",
          );
          setVersionLocked(true);
          return;
        }
        const message =
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Eliminazione fallita";
        toast.error(message);
      },
    });
  }

  const nextVersionLabel =
    metricsSet != null ? `Crea versione ${metricsSet.version + 1}` : "Crea versione";

  const columns: DataTableColumn<EntryRow>[] = useMemo(
    () => [
      {
        id: "kind",
        header: "Metrica",
        headerClassName: "w-[160px]",
        cell: (row) => (
          <Badge variant="secondary" className="font-mono text-xs">
            {kindLabel(row.kind)}
          </Badge>
        ),
      },
      {
        id: "enabled",
        header: "Abilitata",
        headerClassName: "w-[88px]",
        cell: (row) => (
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={row.enabled}
            disabled={editsBlocked || removeEntry.isPending}
            aria-label={`Abilita ${row.kind}`}
            onChange={(e) => toggleEnabled(row, e.target.checked)}
            onClick={(e) => e.stopPropagation()}
          />
        ),
      },
      {
        id: "threshold",
        header: "Soglia",
        headerClassName: "w-[140px]",
        cell: (row) => (
          <Input
            type="number"
            step="any"
            className="h-8 font-mono text-xs"
            placeholder="—"
            value={
              thresholdDraft[row.id] ??
              (row.threshold == null ? "" : String(row.threshold))
            }
            disabled={editsBlocked || removeEntry.isPending}
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
        id: "evaluator",
        header: "Evaluator",
        cell: (row) => (
          <span className="text-sm text-foreground">
            {row.evaluator_id
              ? resolveLabel(
                  row.evaluator_id,
                  evaluatorNameById,
                  "Unknown evaluator",
                )
              : "—"}
          </span>
        ),
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
              aria-label={`Rimuovi ${row.kind}`}
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
      metricsSet,
      evaluatorNameById,
    ],
  );

  if (query.isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (query.isError) {
    const err = query.error;
    const message =
      err instanceof ApiError
        ? `${err.status}: ${err.message}`
        : err instanceof Error
          ? err.message
          : "Unknown error";
    return (
      <ErrorState
        title="Impossibile caricare il set metriche"
        message={message}
        onRetry={() => query.refetch()}
      />
    );
  }

  if (!metricsSet) {
    return null;
  }

  const backHref = withProjectQuery("/metrics", projectId);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              nativeButton={false}
              render={<Link href={backHref} />}
            >
              <ArrowLeft className="size-4" />
              Indietro
            </Button>
            <h1 className="text-lg font-semibold text-foreground">
              {metricsSet.name}
            </h1>
            <span className="rounded-md border border-border bg-surface px-2 py-0.5 font-mono text-xs text-muted-foreground">
              v{metricsSet.version}
            </span>
            {metricsSet.is_project_default ? (
              <Badge variant="secondary">Default progetto</Badge>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            {metricsSet.description ? (
              <span className="max-w-xl">{metricsSet.description}</span>
            ) : null}
            <span>
              Voci{" "}
              <span className="font-mono tabular-nums text-foreground">
                {metricsSet.entry_count}
              </span>
            </span>
            <span>
              Aggiornato <RelativeTime date={metricsSet.updated_at} />
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant={versionLocked ? "default" : "outline"}
            disabled={version.isPending}
            onClick={() => {
              version.mutate(undefined, {
                onSuccess: (created) => {
                  toast.success("Nuova versione creata");
                  router.push(
                    `/metrics/${encodeURIComponent(created.id)}?project=${encodeURIComponent(projectId)}`,
                  );
                },
                onError: (err) => {
                  const message =
                    err instanceof ApiError
                      ? err.message
                      : err instanceof Error
                        ? err.message
                        : "Versione fallita";
                  toast.error(message);
                },
              });
            }}
          >
            <GitBranchPlus className="size-4" />
            {version.isPending ? "Creazione…" : nextVersionLabel}
          </Button>
          <RefreshControl
            queryKey={queryOpts.queryKey}
            dataUpdatedAt={query.dataUpdatedAt}
          />
        </div>
      </div>

      {versionLocked ? (
        <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-foreground">
          Questo set è referenziato da una o più run: usa «{nextVersionLabel}» per
          modificare le metriche senza alterare le run esistenti.
        </p>
      ) : null}

      {rows.length === 0 ? (
        <EmptyState
          title="Set vuoto"
          description="Nessuna voce metrica in questo set."
        />
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          getRowKey={(row) => row.id}
          selectedIndex={selectedIndex}
          onSelectedIndexChange={setSelectedIndex}
          onRowActivate={() => {}}
          aria-label="Voci set metriche"
        />
      )}
    </div>
  );
}
