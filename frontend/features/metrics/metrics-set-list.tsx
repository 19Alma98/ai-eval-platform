"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState, type SubmitEvent } from "react";
import { PackagePlus, Plus } from "lucide-react";
import { toast } from "sonner";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { PageIntro } from "@/components/page-intro";
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
import { formatErrorForUi } from "@/lib/api/client";
import { ensureMetricsPack } from "@/lib/api/metrics-packs";
import { getMetricsSet, listMetricsSets } from "@/lib/api/metrics-sets";
import type { MetricsSetEntryInput, MetricsSetSummary } from "@/lib/api/types";
import {
  metricsSetsQueryOptions,
  useCreateMetricsSet,
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

  const rows = useMemo(() => query.data ?? [], [query.data]);

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
        header: "Name",
        cell: (row) => (
          <span className="flex min-w-0 flex-col">
            <span className="truncate font-medium text-foreground">{row.name}</span>
            {row.description ? (
              <span className="truncate text-xs text-muted-foreground">{row.description}</span>
            ) : null}
          </span>
        ),
      },
      {
        id: "version",
        header: "Version",
        headerClassName: "w-[88px]",
        className: "tabular-nums text-muted-foreground",
        cell: (row) => `v${row.version}`,
      },
      {
        id: "default",
        header: "Used by default",
        headerClassName: "w-[160px]",
        cell: (row) =>
          row.is_project_default ? (
            <Badge variant="secondary">Project default</Badge>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
      {
        id: "enabled",
        header: "Active metrics",
        headerClassName: "w-[140px]",
        className: "tabular-nums text-muted-foreground",
        cell: (row) => `${row.enabled_count} of ${row.entry_count}`,
      },
    ],
    [],
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

  return (
    <div className="flex flex-col gap-3">
      <PageIntro
        title="Metrics"
        glossary="What “good” means for your app: the metrics every experiment is scored on and the minimum score each answer needs to pass."
        actions={
          <>
            <RefreshControl
              queryKey={queryOpts.queryKey}
              dataUpdatedAt={query.dataUpdatedAt}
            />
            {rows.length > 0 ? (
              <CreateMetricsSetDialog
                projectId={projectId}
                open={createOpen}
                onOpenChange={setCreateOpen}
              />
            ) : null}
          </>
        }
      />

      {rows.length === 0 ? (
        <EmptyState
          title="No metrics yet"
          description="Start with the recommended RAG metrics: correctness, groundedness, answer relevance, retrieval quality and latency. You can change thresholds later."
          action={
            <Button
              type="button"
              size="sm"
              disabled={ensure.isPending}
              onClick={() => {
                ensure.mutate(undefined, {
                  onSuccess: () => toast.success("Recommended metrics added"),
                  onError: (e) => {
                    const message = formatErrorForUi(e);
                    toast.error(message);
                  },
                });
              }}
            >
              <PackagePlus className="size-4" />
              {ensure.isPending ? "Adding…" : "Add recommended metrics"}
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
          aria-label="Metrics sets"
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
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const createSet = useCreateMetricsSet(projectId);

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    void (async () => {
      try {
        const entries = await seedEntriesForCreate(projectId);
        await createSet.mutateAsync({
          name: name.trim(),
          description: description.trim() || null,
          entries,
        });
        toast.success("Metrics set created");
        setName("");
        setDescription("");
        onOpenChange(false);
      } catch (err) {
        const message = formatErrorForUi(err);
        toast.error(message);
      }
    })();
  }

  const pending = createSet.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger
        render={
          <Button type="button" size="sm">
            <Plus className="size-4" />
            New metrics set
          </Button>
        }
      />
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>New metrics set</DialogTitle>
            <DialogDescription>
              Starts as a copy of the project default. Use it to try stricter
              thresholds without changing the default.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-4">
            <div className="flex flex-col gap-2">
              <label htmlFor="metrics-set-create-name" className="text-sm font-medium">
                Name
              </label>
              <Input
                id="metrics-set-create-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Strict release bar"
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <label
                htmlFor="metrics-set-create-description"
                className="text-sm font-medium"
              >
                Description
              </label>
              <Textarea
                id="metrics-set-create-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional"
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
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || pending}>
              {pending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
