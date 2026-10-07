"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState, type SubmitEvent } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { DataTable, type DataTableColumn } from "@/components/data-table";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { RefreshControl } from "@/components/refresh-control";
import { RelativeTime } from "@/components/relative-time";
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
import { createDataset } from "@/lib/api/datasets";
import type { Dataset } from "@/lib/api/types";
import { useProjectId } from "@/lib/project-store";
import { ImportDatasetDialog } from "./import-dataset-dialog";
import { RAG_QA_TASK } from "./rag-qa";
import {
  datasetsQueryKey,
  datasetsQueryOptions,
  useDatasets,
} from "./use-datasets";

export function DatasetList() {
  const router = useRouter();
  const { projectId } = useProjectId();
  const query = useDatasets(projectId);
  const queryOpts = projectId ? datasetsQueryOptions(projectId) : null;
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  const rows = query.data ?? [];

  const onRowActivate = useCallback(
    (dataset: Dataset) => {
      if (!projectId) return;
      router.push(
        `/datasets/${encodeURIComponent(dataset.id)}?project=${encodeURIComponent(projectId)}`,
      );
    },
    [projectId, router],
  );

  const selectedDataset = rows[selectedIndex] ?? null;

  const columns: DataTableColumn<Dataset>[] = useMemo(
    () => [
      {
        id: "name",
        header: "Name",
        cell: (row) => (
          <span className="font-medium text-foreground">{row.name}</span>
        ),
      },
      {
        id: "version",
        header: "Version",
        headerClassName: "w-[88px]",
        className: "font-mono tabular-nums text-muted-foreground",
        cell: (row) => row.version,
      },
      {
        id: "description",
        header: "Description",
        cell: (row) => (
          <span className="line-clamp-2 text-sm text-muted-foreground">
            {row.description?.trim() || "—"}
          </span>
        ),
      },
      {
        id: "created",
        header: "Created",
        headerClassName: "w-[120px]",
        cell: (row) => <RelativeTime date={row.created_at} />,
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
        title="Could not load test sets"
        message={message}
        onRetry={() => query.refetch()}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="sticky top-0 z-20 -mx-1 flex flex-wrap items-center gap-3 border-b border-border bg-background px-1 pb-3">
        <div className="flex-1" />
        {projectId && selectedDataset ? (
          <ImportDatasetDialog
            projectId={projectId}
            datasetId={selectedDataset.id}
            datasetName={selectedDataset.name}
            taskType={selectedDataset.task_type}
            open={importOpen}
            onOpenChange={setImportOpen}
          />
        ) : null}
        {projectId && rows.length > 0 ? (
          <CreateDatasetDialog
            projectId={projectId}
            open={createOpen}
            onOpenChange={setCreateOpen}
          />
        ) : null}
        {queryOpts ? (
          <RefreshControl
            queryKey={queryOpts.queryKey}
            dataUpdatedAt={query.dataUpdatedAt}
          />
        ) : null}
      </div>

      {rows.length === 0 ? (
        <EmptyState
          title="No test sets yet"
          description="Create a RAG Q&A test set to collect questions, answers, and gold document ids for evaluation."
          action={
            projectId ? (
              <CreateDatasetDialog
                projectId={projectId}
                open={createOpen}
                onOpenChange={setCreateOpen}
              />
            ) : null
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
          aria-label="Test set"
        />
      )}
    </div>
  );
}

function CreateDatasetDialog({
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
  const [version, setVersion] = useState("1");

  const create = useMutation({
    mutationFn: () =>
      createDataset(projectId, {
        name: name.trim(),
        description: description.trim() || undefined,
        version: Number.parseInt(version, 10) || 1,
        task_type: RAG_QA_TASK,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: datasetsQueryKey(projectId),
      });
      toast.success("Dataset created");
      setName("");
      setDescription("");
      setVersion("1");
      onOpenChange(false);
    },
    onError: (err) => {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Create failed";
      toast.error(message);
    },
  });

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    create.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger
        render={
          <Button type="button" size="sm">
            <Plus className="size-4" />
            New dataset
          </Button>
        }
      />
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Create dataset</DialogTitle>
            <DialogDescription>
              Versioned collections of questions, expected answers, and gold
              document ids for RAG evaluation.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-4">
            <div className="flex flex-col gap-2">
              <label htmlFor="dataset-create-name" className="text-sm font-medium">
                Name
              </label>
              <Input
                id="dataset-create-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My eval set"
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <label
                htmlFor="dataset-create-description"
                className="text-sm font-medium"
              >
                Description
              </label>
              <Textarea
                id="dataset-create-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional notes"
                rows={3}
              />
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="dataset-create-version" className="text-sm font-medium">
                Version
              </label>
              <Input
                id="dataset-create-version"
                type="number"
                min={1}
                value={version}
                onChange={(e) => setVersion(e.target.value)}
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
            <Button type="submit" disabled={!name.trim() || create.isPending}>
              {create.isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
