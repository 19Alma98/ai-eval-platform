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
import { PageIntro } from "@/components/page-intro";
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
import { formatErrorForUi } from "@/lib/api/client";
import { createDataset } from "@/lib/api/datasets";
import { useProjectId } from "@/lib/project-store";
import { groupDatasetVersions, type DatasetRow } from "./dataset-versions";
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

  const rows = useMemo(() => groupDatasetVersions(query.data ?? []), [query.data]);

  const onRowActivate = useCallback(
    (dataset: DatasetRow) => {
      if (!projectId) return;
      router.push(
        `/datasets/${encodeURIComponent(dataset.id)}?project=${encodeURIComponent(projectId)}`,
      );
    },
    [projectId, router],
  );

  const columns: DataTableColumn<DatasetRow>[] = useMemo(
    () => [
      {
        id: "name",
        header: "Name",
        cell: (row) =>
          row.latest ? (
            <span className="font-medium text-foreground">{row.name}</span>
          ) : (
            <span className="pl-4 text-muted-foreground">
              <span aria-hidden>↳ </span>
              <span className="sr-only">{row.name}, </span>older version
            </span>
          ),
      },
      {
        id: "version",
        header: "Version",
        headerClassName: "w-[120px]",
        className: "tabular-nums text-muted-foreground",
        cell: (row) =>
          row.latest && row.versionCount > 1 ? (
            <span title={`${row.versionCount} versions; older ones are listed below`}>
              v{row.version} <span className="text-xs">(latest)</span>
            </span>
          ) : (
            `v${row.version}`
          ),
      },
      {
        id: "questions",
        header: "Questions",
        headerClassName: "w-[96px] text-right",
        className: "text-right tabular-nums",
        cell: (row) => (row.item_count != null ? row.item_count.toLocaleString() : "—"),
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
    const message = formatErrorForUi(err);
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
      <PageIntro
        title="Test sets"
        glossary="Questions your app should answer well, with the expected answer and the documents that contain it."
        actions={
          <>
            {queryOpts ? (
              <RefreshControl
                queryKey={queryOpts.queryKey}
                dataUpdatedAt={query.dataUpdatedAt}
              />
            ) : null}
            {projectId && rows.length > 0 ? (
              <CreateDatasetDialog
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
          title="No test sets yet"
          description="A test set is a list of questions with the answer you expect and the documents that should be retrieved. Create one, then import a CSV or JSON file."
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
          aria-label="Test sets"
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

  const create = useMutation({
    mutationFn: () =>
      createDataset(projectId, {
        name: name.trim(),
        description: description.trim() || undefined,
        version: 1,
        task_type: RAG_QA_TASK,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: datasetsQueryKey(projectId),
      });
      toast.success("Test set created");
      setName("");
      setDescription("");
      onOpenChange(false);
    },
    onError: (err) => {
      const message = formatErrorForUi(err);
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
            New test set
          </Button>
        }
      />
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>New test set</DialogTitle>
            <DialogDescription>
              Give it a name. You can add questions right after, by importing a
              CSV or JSON file.
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
                placeholder="e.g. HR policy questions"
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
