"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";
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
import {
  useAppConfigAliases,
  useAppConfigVersions,
  useAppConfigs,
} from "@/features/app-configs/use-app-configs";
import { useDatasets } from "@/features/datasets/use-datasets";
import { taskTypeLabel, useTaskTypes } from "@/features/datasets/use-task-types";
import { experimentsQueryKey } from "./use-experiments";

type ModelSource = "free" | "app-config";
type AppConfigPick = "alias" | "family";

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
  const appConfigsQuery = useAppConfigs(projectId);
  const aliasesQuery = useAppConfigAliases(projectId);
  const datasets = datasetsQuery.data ?? [];
  const hasDatasets = datasets.length > 0;

  const [name, setName] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [modelSource, setModelSource] = useState<ModelSource>("free");
  const [model, setModel] = useState("");
  const [version, setVersion] = useState("");
  const [appConfigPick, setAppConfigPick] = useState<AppConfigPick>("alias");
  const [selectedAlias, setSelectedAlias] = useState("");
  const [selectedFamily, setSelectedFamily] = useState("");
  const [selectedConfigId, setSelectedConfigId] = useState("");

  const versionsQuery = useAppConfigVersions(
    modelSource === "app-config" && appConfigPick === "family" ? projectId : null,
    selectedFamily || null,
  );

  const familyNames = useMemo(() => {
    const names = new Set<string>();
    for (const c of appConfigsQuery.data ?? []) {
      names.add(c.name);
    }
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [appConfigsQuery.data]);

  const aliases = aliasesQuery.data ?? [];

  const create = useMutation({
    mutationFn: () => {
      const versionTrimmed = version.trim();
      const base = {
        name: name.trim(),
        dataset_id: datasetId,
        ...(versionTrimmed ? { version: versionTrimmed } : {}),
      };

      if (modelSource === "app-config") {
        if (appConfigPick === "alias") {
          return createExperiment(projectId, {
            ...base,
            app_config_alias: selectedAlias,
          });
        }
        return createExperiment(projectId, {
          ...base,
          app_config_id: selectedConfigId,
        });
      }

      const modelTrimmed = model.trim();
      return createExperiment(projectId, {
        ...base,
        ...(modelTrimmed ? { model_config: { model: modelTrimmed } } : {}),
      });
    },
    onSuccess: async (experiment) => {
      await queryClient.invalidateQueries({
        queryKey: experimentsQueryKey(projectId),
      });
      toast.success("Experiment created");
      setName("");
      setDatasetId("");
      setModelSource("free");
      setModel("");
      setVersion("");
      setAppConfigPick("alias");
      setSelectedAlias("");
      setSelectedFamily("");
      setSelectedConfigId("");
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
    if (!canSubmit) return;
    create.mutate();
  }

  const appConfigReady =
    modelSource !== "app-config" ||
    (appConfigPick === "alias"
      ? Boolean(selectedAlias)
      : Boolean(selectedFamily && selectedConfigId));

  const canSubmit = Boolean(name.trim() && datasetId && hasDatasets && appConfigReady);

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
                    const label = taskTypeLabel(taskTypesQuery.data, d.task_type);
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
              <label htmlFor="experiment-create-model-source" className="text-sm font-medium">
                Model configuration
              </label>
              <Select
                value={modelSource}
                onValueChange={(v) => {
                  const next = (v ?? "free") as ModelSource;
                  setModelSource(next);
                  if (next === "free") {
                    setSelectedAlias("");
                    setSelectedFamily("");
                    setSelectedConfigId("");
                  } else {
                    setModel("");
                  }
                }}
              >
                <SelectTrigger id="experiment-create-model-source">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="free">Free-form model</SelectItem>
                  <SelectItem value="app-config">App config (registry)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {modelSource === "free" ? (
              <>
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
              </>
            ) : (
              <>
                <div className="flex flex-col gap-2">
                  <label htmlFor="experiment-create-app-pick" className="text-sm font-medium">
                    Registry reference
                  </label>
                  <Select
                    value={appConfigPick}
                    onValueChange={(v) => {
                      const next = (v ?? "alias") as AppConfigPick;
                      setAppConfigPick(next);
                      setSelectedAlias("");
                      setSelectedFamily("");
                      setSelectedConfigId("");
                    }}
                  >
                    <SelectTrigger id="experiment-create-app-pick">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="alias">Alias</SelectItem>
                      <SelectItem value="family">Family + version</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {appConfigPick === "alias" ? (
                  <div className="flex flex-col gap-2">
                    <label htmlFor="experiment-create-alias" className="text-sm font-medium">
                      Alias
                    </label>
                    <Select
                      value={selectedAlias}
                      onValueChange={(v) => setSelectedAlias(v ?? "")}
                      disabled={aliases.length === 0}
                    >
                      <SelectTrigger id="experiment-create-alias">
                        <SelectValue placeholder="Select alias" />
                      </SelectTrigger>
                      <SelectContent>
                        {aliases.map((a) => (
                          <SelectItem key={a.name} value={a.name}>
                            {a.name} → {a.app_config.name}@v{a.app_config.version}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {aliases.length === 0 ? (
                      <p className="text-xs text-muted-foreground">
                        No aliases yet —{" "}
                        <Link
                          href={withProjectQuery("/app-configs", projectId)}
                          className="text-primary hover:underline"
                        >
                          set up app configs
                        </Link>
                        .
                      </p>
                    ) : null}
                  </div>
                ) : (
                  <>
                    <div className="flex flex-col gap-2">
                      <label htmlFor="experiment-create-family" className="text-sm font-medium">
                        Config family
                      </label>
                      <Select
                        value={selectedFamily}
                        onValueChange={(v) => {
                          setSelectedFamily(v ?? "");
                          setSelectedConfigId("");
                        }}
                        disabled={familyNames.length === 0}
                      >
                        <SelectTrigger id="experiment-create-family">
                          <SelectValue placeholder="Select family" />
                        </SelectTrigger>
                        <SelectContent>
                          {familyNames.map((family) => (
                            <SelectItem key={family} value={family}>
                              {family}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex flex-col gap-2">
                      <label htmlFor="experiment-create-config-version" className="text-sm font-medium">
                        Version
                      </label>
                      <Select
                        value={selectedConfigId}
                        onValueChange={(v) => setSelectedConfigId(v ?? "")}
                        disabled={!selectedFamily || (versionsQuery.data ?? []).length === 0}
                      >
                        <SelectTrigger id="experiment-create-config-version">
                          <SelectValue placeholder="Select version" />
                        </SelectTrigger>
                        <SelectContent>
                          {(versionsQuery.data ?? []).map((c) => (
                            <SelectItem key={c.id} value={c.id}>
                              v{c.version}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    {familyNames.length === 0 ? (
                      <p className="text-xs text-muted-foreground">
                        No app configs yet —{" "}
                        <Link
                          href={withProjectQuery("/app-configs", projectId)}
                          className="text-primary hover:underline"
                        >
                          create one
                        </Link>
                        .
                      </p>
                    ) : null}
                  </>
                )}
                <div className="flex flex-col gap-2">
                  <label htmlFor="experiment-create-run-version" className="text-sm font-medium">
                    Run label{" "}
                    <span className="font-normal text-muted-foreground">(optional)</span>
                  </label>
                  <Input
                    id="experiment-create-run-version"
                    value={version}
                    onChange={(e) => setVersion(e.target.value)}
                    placeholder="v1.2, prompt-rev-3, git sha…"
                  />
                </div>
              </>
            )}
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
