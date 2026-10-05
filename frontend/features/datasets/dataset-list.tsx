"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState, type FormEvent } from "react";
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
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  datasetsQueryKey,
  datasetsQueryOptions,
  useDatasets,
} from "./use-datasets";
import { taskTypeLabel, useTaskTypes } from "./use-task-types";

export function DatasetList() {
  const router = useRouter();
  const { projectId } = useProjectId();
  const query = useDatasets(projectId);
  const taskTypesQuery = useTaskTypes();
  const queryOpts = projectId ? datasetsQueryOptions(projectId) : null;
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [taskFilter, setTaskFilter] = useState<string>("all");

  const allRows = query.data ?? [];
  const rows = useMemo(() => {
    if (taskFilter === "all") return allRows;
    if (taskFilter === "none") {
      return allRows.filter((d) => !d.task_type);
    }
    return allRows.filter((d) => d.task_type === taskFilter);
  }, [allRows, taskFilter]);

  const onRowActivate = useCallback(
    (dataset: Dataset) => {
      if (!projectId) return;
      router.push(
        `/datasets/${encodeURIComponent(dataset.id)}?project=${encodeURIComponent(projectId)}`,
      );
    },
    [projectId, router],
  );

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
        id: "task_type",
        header: "Task",
        headerClassName: "w-[140px]",
        cell: (row) => {
          const label = taskTypeLabel(taskTypesQuery.data, row.task_type);
          return label ? (
            <Badge variant="secondary">{label}</Badge>
          ) : (
            <span className="text-muted-foreground">—</span>
          );
        },
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
    [taskTypesQuery.data],
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
        <div className="w-[200px]">
          <Select
            value={taskFilter}
            onValueChange={(v) => {
              setTaskFilter(v ?? "all");
              setSelectedIndex(0);
            }}
          >
            <SelectTrigger aria-label="Filter by task type">
              <SelectValue placeholder="All tasks" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All tasks</SelectItem>
              <SelectItem value="none">Untyped</SelectItem>
              {(taskTypesQuery.data ?? []).map((t) => (
                <SelectItem key={t.id} value={t.id}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex-1" />
        {projectId && allRows.length > 0 ? (
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

      {allRows.length === 0 ? (
        <EmptyState
          title="No test sets yet"
          description="Create a test set to collect trace examples for evaluation. Optionally set a task type for focused hints."
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
      ) : rows.length === 0 ? (
        <EmptyState
          title="No matches"
          description="No test sets match this task filter."
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
  const taskTypesQuery = useTaskTypes();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [version, setVersion] = useState("1");
  const [taskType, setTaskType] = useState<string>("none");

  const selectedTask =
    taskType === "none"
      ? null
      : (taskTypesQuery.data ?? []).find((t) => t.id === taskType) ?? null;

  const create = useMutation({
    mutationFn: () =>
      createDataset(projectId, {
        name: name.trim(),
        description: description.trim() || undefined,
        version: Number.parseInt(version, 10) || 1,
        ...(taskType !== "none" ? { task_type: taskType } : {}),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: datasetsQueryKey(projectId),
      });
      toast.success("Dataset created");
      setName("");
      setDescription("");
      setVersion("1");
      setTaskType("none");
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

  function handleSubmit(e: FormEvent) {
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
              Versioned collections of inputs and expected outputs for eval runs.
              Task type is optional guidance only.
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
              <label className="text-sm font-medium">Task type</label>
              <Select value={taskType} onValueChange={(v) => setTaskType(v ?? "none")}>
                <SelectTrigger aria-label="Task type">
                  <SelectValue placeholder="Generic" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Generic (no type)</SelectItem>
                  {(taskTypesQuery.data ?? []).map((t) => (
                    <SelectItem key={t.id} value={t.id}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedTask ? (
                <ul className="list-inside list-disc text-xs text-muted-foreground">
                  {selectedTask.field_hints.map((hint) => (
                    <li key={hint}>{hint}</li>
                  ))}
                </ul>
              ) : null}
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
