"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type SubmitEvent } from "react";
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
import { formatErrorForUi } from "@/lib/api/client";
import { createExperiment } from "@/lib/api/experiments";
import { withProjectQuery } from "@/lib/project-href";
import {
  useAppConfigAliases,
  useAppConfigVersions,
  useAppConfigs,
} from "@/features/app-configs/use-app-configs";
import { useDatasets } from "@/features/datasets/use-datasets";
import {
  metricsSetIdForCreate,
  PROJECT_DEFAULT_SELECT,
} from "@/features/metrics/metrics-set-submit";
import { useMetricsSets } from "@/features/metrics/use-metrics-sets";
import { experimentsQueryKey } from "./use-experiments";

type AppConfigPick = "none" | "alias" | "family";

function defaultAppConfigPick(
  aliasCount: number,
  familyCount: number,
): AppConfigPick {
  if (aliasCount > 0) return "alias";
  if (familyCount > 0) return "family";
  return "none";
}

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
  const metricsSetsQuery = useMetricsSets(projectId);
  const appConfigsQuery = useAppConfigs(projectId);
  const aliasesQuery = useAppConfigAliases(projectId);
  const datasets = datasetsQuery.data ?? [];
  const hasDatasets = datasets.length > 0;

  const [name, setName] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [appConfigPick, setAppConfigPick] = useState<AppConfigPick>("none");
  const [model, setModel] = useState("");
  const [version, setVersion] = useState("");
  const [selectedAlias, setSelectedAlias] = useState("");
  const [selectedFamily, setSelectedFamily] = useState("");
  const [selectedConfigId, setSelectedConfigId] = useState("");
  const [selectedMetricsSet, setSelectedMetricsSet] = useState(
    PROJECT_DEFAULT_SELECT,
  );
  const defaultPickApplied = useRef(false);

  const metricsSets = metricsSetsQuery.data ?? [];
  const aliases = aliasesQuery.data ?? [];

  const familyNames = useMemo(() => {
    const names = new Set<string>();
    for (const c of appConfigsQuery.data ?? []) {
      names.add(c.name);
    }
    return [...names].sort((a, b) => a.localeCompare(b));
  }, [appConfigsQuery.data]);

  const registryReady =
    !appConfigsQuery.isLoading && !aliasesQuery.isLoading;

  useEffect(() => {
    if (!open || !registryReady || defaultPickApplied.current) return;
    setAppConfigPick(defaultAppConfigPick(aliases.length, familyNames.length));
    defaultPickApplied.current = true;
  }, [open, registryReady, aliases.length, familyNames.length]);

  useEffect(() => {
    if (!open) {
      defaultPickApplied.current = false;
    }
  }, [open]);

  const versionsQuery = useAppConfigVersions(
    appConfigPick === "family" ? projectId : null,
    selectedFamily || null,
  );

  const create = useMutation({
    mutationFn: () => {
      const versionTrimmed = version.trim();
      const metricsSetId = metricsSetIdForCreate(selectedMetricsSet);
      const base = {
        name: name.trim(),
        dataset_id: datasetId,
        ...(metricsSetId != null ? { metrics_set_id: metricsSetId } : {}),
      };

      if (appConfigPick === "alias") {
        return createExperiment(projectId, {
          ...base,
          app_config_alias: selectedAlias,
        });
      }
      if (appConfigPick === "family") {
        return createExperiment(projectId, {
          ...base,
          app_config_id: selectedConfigId,
        });
      }

      const modelTrimmed = model.trim();
      return createExperiment(projectId, {
        ...base,
        ...(versionTrimmed ? { version: versionTrimmed } : {}),
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
      setAppConfigPick("none");
      setModel("");
      setVersion("");
      setSelectedAlias("");
      setSelectedFamily("");
      setSelectedConfigId("");
      setSelectedMetricsSet(PROJECT_DEFAULT_SELECT);
      defaultPickApplied.current = false;
      onOpenChange(false);
      router.push(
        withProjectQuery(`/experiments/${encodeURIComponent(experiment.id)}`, projectId),
      );
    },
    onError: (err) => {
      const message = formatErrorForUi(err);
      toast.error(message);
    },
  });

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    create.mutate();
  }

  function selectAppConfigPick(next: AppConfigPick) {
    setAppConfigPick(next);
    setSelectedAlias("");
    setSelectedFamily("");
    setSelectedConfigId("");
    if (next !== "none") {
      setModel("");
      setVersion("");
    }
  }

  const appConfigReady =
    appConfigPick === "none" ||
    (appConfigPick === "alias"
      ? Boolean(selectedAlias)
      : Boolean(selectedFamily && selectedConfigId));

  const canSubmit = Boolean(name.trim() && datasetId && hasDatasets && appConfigReady);
  const hasRegistry = aliases.length > 0 || familyNames.length > 0;

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
                  {datasets.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {d.name} (v{d.version})
                    </SelectItem>
                  ))}
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
              <label htmlFor="experiment-create-app-pick" className="text-sm font-medium">
                App config{" "}
                <span className="font-normal text-muted-foreground">(optional)</span>
              </label>
              <p className="text-xs text-muted-foreground">
                Versioned prompt, model, and retrieval settings for this run.
              </p>
              <Select
                value={appConfigPick}
                onValueChange={(v) =>
                  selectAppConfigPick((v ?? "none") as AppConfigPick)
                }
              >
                <SelectTrigger id="experiment-create-app-pick">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None — use advanced below</SelectItem>
                  <SelectItem value="alias" disabled={aliases.length === 0}>
                    Alias
                  </SelectItem>
                  <SelectItem value="family" disabled={familyNames.length === 0}>
                    Family + version
                  </SelectItem>
                </SelectContent>
              </Select>
              {!hasRegistry ? (
                <p className="text-xs text-muted-foreground">
                  No app configs in this project yet. Register them from your app
                  via the SDK or API, then refresh. Or use Advanced below.
                </p>
              ) : null}
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
              </div>
            ) : null}
            {appConfigPick === "family" ? (
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
                  <label
                    htmlFor="experiment-create-config-version"
                    className="text-sm font-medium"
                  >
                    Config version
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
              </>
            ) : null}
            <div className="flex flex-col gap-2">
              <label htmlFor="experiment-create-metrics-set" className="text-sm font-medium">
                Metrics set
              </label>
              <Select
                value={selectedMetricsSet}
                onValueChange={(v) =>
                  setSelectedMetricsSet(v ?? PROJECT_DEFAULT_SELECT)
                }
              >
                <SelectTrigger id="experiment-create-metrics-set">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={PROJECT_DEFAULT_SELECT}>
                    Default progetto (fallback)
                  </SelectItem>
                  {metricsSets.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name} v{s.version}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {appConfigPick === "none" ? (
              <details className="rounded-md border border-border px-3 py-2" open>
                <summary className="cursor-pointer text-sm font-medium text-foreground">
                  Advanced — without registry
                </summary>
                <div className="mt-3 flex flex-col gap-3">
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
              </details>
            ) : null}
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
