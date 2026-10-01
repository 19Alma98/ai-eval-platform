"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api/client";
import {
  addItemFromTrace,
  createDataset,
  listDatasets,
} from "@/lib/api/datasets";
import { LoadingBlock } from "@/components/loading-block";
import { datasetQueryKey } from "@/features/datasets/use-datasets";

type AddToDatasetDialogProps = {
  projectId: string;
  traceId: string;
  sourceSpanId?: string | null;
  trigger?: React.ReactNode;
};

export function AddToDatasetDialog({
  projectId,
  traceId,
  sourceSpanId,
  trigger,
}: AddToDatasetDialogProps) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [datasetId, setDatasetId] = useState<string>("");
  const [newName, setNewName] = useState("");
  const queryClient = useQueryClient();

  const datasetsQuery = useQuery({
    queryKey: ["datasets", projectId],
    queryFn: () => listDatasets(projectId),
    enabled: open && Boolean(projectId),
  });

  const mutation = useMutation({
    mutationFn: async () => {
      let targetId = datasetId;
      if (mode === "new") {
        const created = await createDataset(projectId, {
          name: newName.trim(),
        });
        targetId = created.id;
      }
      if (!targetId) throw new Error("Select or create a dataset");
      return addItemFromTrace(targetId, {
        trace_id: traceId,
        ...(sourceSpanId ? { source_span_id: sourceSpanId } : {}),
      });
    },
    onSuccess: (item) => {
      queryClient.invalidateQueries({ queryKey: ["datasets", projectId] });
      queryClient.invalidateQueries({ queryKey: datasetQueryKey(item.dataset_id) });
      toast.success("Added trace to dataset");
      setOpen(false);
      setNewName("");
    },
    onError: (err) => {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Could not add to dataset";
      toast.error(message);
    },
  });

  const canSubmit =
    mode === "existing"
      ? Boolean(datasetId)
      : newName.trim().length > 0;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {trigger ? (
        <DialogTrigger render={trigger as React.ReactElement} />
      ) : (
        <DialogTrigger render={<Button type="button" variant="outline" size="sm" />}>
          Add to dataset
        </DialogTrigger>
      )}
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add to dataset</DialogTitle>
          <DialogDescription>
            Promote this trace{sourceSpanId ? " (selected span)" : ""} into a
            dataset item for evaluation.
          </DialogDescription>
        </DialogHeader>

        {datasetsQuery.isLoading ? (
          <LoadingBlock className="min-h-[120px]" />
        ) : (
          <div className="flex flex-col gap-4 py-2">
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                variant={mode === "existing" ? "default" : "outline"}
                onClick={() => setMode("existing")}
              >
                Existing
              </Button>
              <Button
                type="button"
                size="sm"
                variant={mode === "new" ? "default" : "outline"}
                onClick={() => setMode("new")}
              >
                New dataset
              </Button>
            </div>

            {mode === "existing" ? (
              <div className="flex flex-col gap-2">
                <label htmlFor="dataset-select" className="text-sm font-medium">
                  Dataset
                </label>
                <Select
                  value={datasetId}
                  onValueChange={(v) => setDatasetId(v ?? "")}
                >
                  <SelectTrigger id="dataset-select">
                    <SelectValue placeholder="Select dataset" />
                  </SelectTrigger>
                  <SelectContent>
                    {(datasetsQuery.data ?? []).map((d) => (
                      <SelectItem key={d.id} value={d.id}>
                        {d.name} (v{d.version})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {(datasetsQuery.data ?? []).length === 0 ? (
                  <p className="text-xs text-muted-foreground">
                    No datasets yet — create one above.
                  </p>
                ) : null}
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                <label htmlFor="dataset-name" className="text-sm font-medium">
                  Name
                </label>
                <Input
                  id="dataset-name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="My eval set"
                />
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => setOpen(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            disabled={!canSubmit || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Adding…" : "Add"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
