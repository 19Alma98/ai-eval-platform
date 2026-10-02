"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Plus } from "lucide-react";
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
import { createExperiment } from "@/lib/api/experiments";
import { withProjectQuery } from "@/lib/project-href";
import { useDatasets } from "@/features/datasets/use-datasets";
import { taskTypeLabel, useTaskTypes } from "@/features/datasets/use-task-types";
import {
  experimentsQueryKey,
} from "./use-experiments";

export function CreateExperimentDialog({
  projectId,
  open,
  onOpenChange,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const datasetsQuery = useDatasets(projectId);
  const taskTypesQuery = useTaskTypes();
  const datasets = datasetsQuery.data ?? [];
  const hasDatasets = datasets.length > 0;

  const [name, setName] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [model, setModel] = useState("");
  const [version, setVersion] = useState("");

  const create = useMutation({
    mutationFn: () => {
      const modelTrimmed = model.trim();
      const versionTrimmed = version.trim();
      return createExperiment(projectId, {
        name: name.trim(),
        dataset_id: datasetId,
        ...(modelTrimmed ? { model_config: { model: modelTrimmed } } : {}),
        ...(versionTrimmed ? { version: versionTrimmed } : {}),
      });
    },
    onSuccess: async (experiment) => {
      await queryClient.invalidateQueries({
        queryKey: experimentsQueryKey(projectId),
      });
      toast.success("Experiment created");
      setName("");
      setDatasetId("");
      setModel("");
      setVersion("");
      onOpenChange(false);
      router.push(
        withProjectQuery(`/experiments/${encodeURIComponent(experiment.id)}`, projectId),
      );
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
    if (!name.trim() || !datasetId || !hasDatasets) return;
    create.mutate();
  }

  const canSubmit = Boolean(name.trim() && datasetId && hasDatasets);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger
        render={
          <Button type="button" size="sm">
            <Plus className="size-4" />
            New experiment
          </Button>
        }
      />
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Create experiment</DialogTitle>
            <DialogDescription>
              Run evaluators against a dataset and compare scores over time.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-4">
            <div className="flex flex-col gap-2">
              <label htmlFor="experiment-create-name" className="text-sm font-medium">
                Name
              </label>
              <Input
                id="experiment-create-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Baseline v1"
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="experiment-create-dataset" className="text-sm font-medium">
                Dataset
              </label>
              <Select
                value={datasetId}
                onValueChange={(v) => setDatasetId(v ?? "")}
                disabled={!hasDatasets}
              >
                <SelectTrigger id="experiment-create-dataset">
                  <SelectValue placeholder="Select dataset" />
                </SelectTrigger>
                <SelectContent>
                  {datasets.map((d) => {
                    const label = taskTypeLabel(
                      taskTypesQuery.data,
                      d.task_type,
                    );
                    return (
                      <SelectItem key={d.id} value={d.id}>
                        {d.name} (v{d.version})
                        {label ? ` · ${label}` : ""}
                      </SelectItem>
                    );
                  })}
                </SelectContent>
              </Select>
              {!hasDatasets ? (
                <p className="text-xs text-muted-foreground">
                  No datasets yet —{" "}
                  <Link
                    href={withProjectQuery("/datasets", projectId)}
                    className="text-primary hover:underline"
                  >
                    create a dataset
                  </Link>{" "}
                  first.
                </p>
              ) : null}
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="experiment-create-model" className="text-sm font-medium">
                Model{" "}
                <span className="font-normal text-muted-foreground">(optional)</span>
              </label>
              <Input
                id="experiment-create-model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="gpt-4o, ollama/gemma4:e2b, …"
              />
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="experiment-create-version" className="text-sm font-medium">
                Version{" "}
                <span className="font-normal text-muted-foreground">(optional)</span>
              </label>
              <Input
                id="experiment-create-version"
                value={version}
                onChange={(e) => setVersion(e.target.value)}
                placeholder="v1.2, prompt-rev-3, git sha…"
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
            <Button type="submit" disabled={!canSubmit || create.isPending}>
              {create.isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
