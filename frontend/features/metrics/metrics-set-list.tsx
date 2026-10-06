"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState, type FormEvent } from "react";
import { PackagePlus, Plus } from "lucide-react";
import { toast } from "sonner";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import { ensureMetricsPack } from "@/lib/api/metrics-packs";
import {
  createMetricsSet,
  getMetricsSet,
  listMetricsSets,
} from "@/lib/api/metrics-sets";
import type { MetricsSetEntryInput, MetricsSetSummary } from "@/lib/api/types";
import {
  metricsSetsQueryKey,
  metricsSetsQueryOptions,
  useEnsureMetricsPackForProject,
  useMetricsSets,
} from "./use-metrics-sets";

function entryInputsFromDefaultSet(
  entries: {
    kind: string;
    enabled: boolean;
    threshold: number | null;
    config: Record<string, unknown>;
    evaluator_id: string | null;
  }[],
): MetricsSetEntryInput[] {
  return entries.map((e) => ({
    kind: e.kind,
    enabled: e.enabled,
    threshold: e.threshold,
    config: e.config,
    evaluator_id: e.evaluator_id,
  }));
}

async function seedEntriesForCreate(projectId: string): Promise<MetricsSetEntryInput[]> {
  await ensureMetricsPack(projectId);
  const sets = await listMetricsSets(projectId);
  const defaultSet = sets.find((s) => s.is_project_default);
  if (!defaultSet) {
    throw new Error("Default metrics set not found after ensure");
  }
  const full = await getMetricsSet(defaultSet.id);
  return entryInputsFromDefaultSet(full.entries);
}

export function MetricsSetList({ projectId }: { projectId: string }) {
  const router = useRouter();
  const query = useMetricsSets(projectId);
  const ensure = useEnsureMetricsPackForProject(projectId);
  const queryOpts = metricsSetsQueryOptions(projectId);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);

  const rows = query.data ?? [];

  const onRowActivate = useCallback(
    (row: MetricsSetSummary) => {
      router.push(
        `/metrics/${encodeURIComponent(row.id)}?project=${encodeURIComponent(projectId)}`,
      );
    },
    [projectId, router],
  );

  const columns: DataTableColumn<MetricsSetSummary>[] = useMemo(
    () => [
      {
        id: "name",
        header: "Nome",
        cell: (row) => (
          <span className="font-medium text-foreground">{row.name}</span>
        ),
      },
      {
        id: "version",
        header: "Versione",
        headerClassName: "w-[88px]",
        className: "font-mono tabular-nums text-muted-foreground",
        cell: (row) => row.version,
      },
      {
        id: "default",
        header: "Default",
        headerClassName: "w-[140px]",
        cell: (row) =>
          row.is_project_default ? (
            <Badge variant="secondary">Default progetto</Badge>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
      {
        id: "enabled",
        header: "Abilitate",
        headerClassName: "w-[100px]",
        className: "font-mono tabular-nums text-muted-foreground",
        cell: (row) => row.enabled_count,
      },
    ],
    [],
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
        title="Impossibile caricare i set metriche"
        message={message}
        onRetry={() => query.refetch()}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="sticky top-0 z-20 -mx-1 flex flex-wrap items-center gap-3 border-b border-border bg-background px-1 pb-3">
        <div className="flex-1" />
        {rows.length > 0 ? (
          <CreateMetricsSetDialog
            projectId={projectId}
            open={createOpen}
            onOpenChange={setCreateOpen}
          />
        ) : null}
        <RefreshControl
          queryKey={queryOpts.queryKey}
          dataUpdatedAt={query.dataUpdatedAt}
        />
      </div>

      {rows.length === 0 ? (
        <EmptyState
          title="Nessun set metriche"
          description="Crea il pack RAG predefinito per questo progetto (hit@k, groundedness, correttezza, latenza)."
          action={
            <Button
              type="button"
              size="sm"
              disabled={ensure.isPending}
              onClick={() => {
                ensure.mutate(undefined, {
                  onSuccess: () => toast.success("Set metriche pronto"),
                  onError: (e) => {
                    const message =
                      e instanceof ApiError
                        ? e.message
                        : e instanceof Error
                          ? e.message
                          : "Creazione fallita";
                    toast.error(message);
                  },
                });
              }}
            >
              <PackagePlus className="size-4" />
              {ensure.isPending ? "Creazione…" : "Crea pack predefinito"}
            </Button>
          }
        />
      ) : (
        <DataTable
          rows={rows}
          columns={columns}
          getRowKey={(row) => row.id}
          selectedIndex={selectedIndex}
          onSelectedIndexChange={setSelectedIndex}
          onRowActivate={onRowActivate}
          aria-label="Set metriche"
        />
      )}
    </div>
  );
}

function CreateMetricsSetDialog({
  projectId,
  open,
  onOpenChange,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const seedAndCreate = useMutation({
    mutationFn: async () => {
      const entries = await seedEntriesForCreate(projectId);
      return createMetricsSet(projectId, {
        name: name.trim(),
        description: description.trim() || null,
        entries,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: metricsSetsQueryKey(projectId),
      });
      toast.success("Set metriche creato");
      setName("");
      setDescription("");
      onOpenChange(false);
    },
    onError: (err) => {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Creazione fallita";
      toast.error(message);
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    seedAndCreate.mutate();
  }

  const pending = seedAndCreate.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger
        render={
          <Button type="button" size="sm">
            <Plus className="size-4" />
            Nuovo set
          </Button>
        }
      />
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Nuovo set metriche</DialogTitle>
            <DialogDescription>
              Copia le voci dal set predefinito del progetto come base
              personalizzabile.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-4">
            <div className="flex flex-col gap-2">
              <label htmlFor="metrics-set-create-name" className="text-sm font-medium">
                Nome
              </label>
              <Input
                id="metrics-set-create-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Il mio set"
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <label
                htmlFor="metrics-set-create-description"
                className="text-sm font-medium"
              >
                Descrizione
              </label>
              <Textarea
                id="metrics-set-create-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Note opzionali"
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Annulla
            </Button>
            <Button type="submit" disabled={!name.trim() || pending}>
              {pending ? "Creazione…" : "Crea"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
