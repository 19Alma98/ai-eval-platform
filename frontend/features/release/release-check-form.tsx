"use client";

import Link from "next/link";
import { dump } from "js-yaml";
import { useMemo, useState, type SubmitEvent } from "react";
import { Copy, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useDataset } from "@/features/datasets/use-datasets";
import { groupableMetadataKeys } from "@/features/experiments/group-compare";
import { isLowerBetter } from "@/features/experiments/metric-direction";
import {
  useExperimentSummary,
  useExperiments,
} from "@/features/experiments/use-experiments";
import { useMetricsSet, useMetricsSets } from "@/features/metrics/use-metrics-sets";
import { formatErrorForUi } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { compareMetrics, metricInfo } from "@/lib/metrics-catalog";
import { withProjectQuery } from "@/lib/project-href";
import { policyFromQualityBar, type QualityBar } from "./describe-check";
import { parsePolicyYaml } from "./parse-policy";
import { ReleaseResult } from "./release-result";
import { useReleaseCheck } from "./use-release";

const NO_BASELINE = "__none__";
const DEFAULT_MIN = "0.7";
const DEFAULT_LATENCY_S = "30";
const DEFAULT_COST_USD = "0.05";
const DEFAULT_GROUPS_MIN_ITEMS = "5";

type ReleaseCheckFormProps = {
  projectId: string;
  initialExperimentId?: string;
};

function Step({
  n,
  title,
  description,
  children,
}: {
  n: number;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-5">
      <div className="flex items-baseline gap-3">
        <span className="w-6 shrink-0 font-serif text-lg text-muted-foreground">{n}.</span>
        <div className="flex flex-col gap-0.5">
          <h2 className="font-serif text-lg font-medium text-foreground">{title}</h2>
          <p className="text-sm text-muted-foreground">{description}</p>
        </div>
      </div>
      <div className="pl-9">{children}</div>
    </section>
  );
}

export function ReleaseCheckForm({
  projectId,
  initialExperimentId = "",
}: ReleaseCheckFormProps) {
  const experimentsQuery = useExperiments(projectId);
  const releaseCheck = useReleaseCheck(projectId);
  const metricsSetsQuery = useMetricsSets(projectId);
  const defaultSetId =
    (metricsSetsQuery.data ?? []).find((s) => s.is_project_default)?.id ?? null;
  const defaultSetQuery = useMetricsSet(defaultSetId);

  const [pickedExperimentId, setExperimentId] = useState(initialExperimentId);
  const [baselinePick, setBaselinePick] = useState<string | null>(null);
  const [ruleEdits, setRuleEdits] = useState<
    Record<string, { enabled?: boolean; min?: string }>
  >({});
  const [latencyEnabled, setLatencyEnabled] = useState(true);
  const [latencyEdit, setLatencySeconds] = useState<string | null>(null);
  const [regressionEnabled, setRegressionEnabled] = useState(true);
  const [regressionPoints, setRegressionPoints] = useState("5");
  const [costEnabled, setCostEnabled] = useState(false);
  const [costMaxUsdEdit, setCostMaxUsd] = useState<string | null>(null);
  const [runMetricEdits, setRunMetricEdits] = useState<
    Record<string, { enabled?: boolean; bound?: string }>
  >({});
  const [groupsEnabled, setGroupsEnabled] = useState(false);
  const [groupsByPick, setGroupsBy] = useState<string | null>(null);
  const [groupsMinItems, setGroupsMinItems] = useState(DEFAULT_GROUPS_MIN_ITEMS);
  const [groupsMaxDeltaPoints, setGroupsMaxDeltaPoints] = useState("");
  const [yamlMode, setYamlMode] = useState(false);
  const [yamlDraft, setYamlDraft] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);

  const experiments = useMemo(() => experimentsQuery.data ?? [], [experimentsQuery.data]);
  // Nothing picked yet: start from the newest finished experiment so the page
  // opens on a real verdict-in-waiting instead of an empty form.
  const latestFinished = useMemo(
    () =>
      [...experiments]
        .filter((e) => e.status.toLowerCase() === "completed")
        .sort((a, b) => b.created_at.localeCompare(a.created_at))[0],
    [experiments],
  );
  const experimentId = pickedExperimentId || latestFinished?.id || "";
  const selectedExperiment = experiments.find((e) => e.id === experimentId);
  const summaryQuery = useExperimentSummary(experimentId || null);
  const datasetQuery = useDataset(selectedExperiment?.dataset_id ?? null);

  const baselineId =
    baselinePick === NO_BASELINE
      ? null
      : (baselinePick ?? selectedExperiment?.baseline_experiment_id ?? null);

  const thresholdByKind = useMemo(() => {
    const map = new Map<string, number>();
    for (const entry of defaultSetQuery.data?.entries ?? []) {
      if (entry.threshold != null) map.set(entry.kind, entry.threshold);
    }
    return map;
  }, [defaultSetQuery.data]);
  // Same budget the latency metric scores against, so the gate and the
  // experiment page never disagree about what "fast enough" means.
  const latencyBudgetMs = defaultSetQuery.data?.entries.find((e) => e.kind === "latency")?.config
    .max_ms;
  const latencySeconds =
    latencyEdit ??
    (typeof latencyBudgetMs === "number" ? String(latencyBudgetMs / 1000) : DEFAULT_LATENCY_S);

  const costBudgetUsd = defaultSetQuery.data?.entries.find((e) => e.kind === "cost")?.config
    .max_usd;
  const costMaxUsd =
    costMaxUsdEdit ??
    (typeof costBudgetUsd === "number" ? String(costBudgetUsd) : DEFAULT_COST_USD);

  const metricNames = useMemo(
    () =>
      [
        ...new Set(
          (summaryQuery.data?.evaluators ?? [])
            .map((e) => e.evaluator_name?.trim() ?? "")
            .filter((n) => n && n !== "latency" && n !== "cost"),
        ),
      ].sort(compareMetrics),
    [summaryQuery.data],
  );
  const hasLatency = (summaryQuery.data?.evaluators ?? []).some(
    (e) => e.evaluator_name === "latency",
  );
  const hasCost = (summaryQuery.data?.evaluators ?? []).some((e) => e.evaluator_name === "cost");

  const experimentMetricKeys = useMemo(
    () => Object.keys(summaryQuery.data?.experiment_metrics ?? {}).sort(),
    [summaryQuery.data],
  );

  const groupKeys = useMemo(
    () => groupableMetadataKeys(datasetQuery.data?.items ?? []),
    [datasetQuery.data?.items],
  );
  const groupsBy = groupsByPick ?? groupKeys[0] ?? "";

  const bar: QualityBar = {
    rules: metricNames.map((name) => ({
      name,
      enabled: ruleEdits[name]?.enabled ?? true,
      min: ruleEdits[name]?.min ?? String(thresholdByKind.get(name) ?? DEFAULT_MIN),
    })),
    latencyEnabled: latencyEnabled && hasLatency,
    latencySeconds,
    regressionEnabled: regressionEnabled && baselineId != null,
    regressionPoints,
    costEnabled: costEnabled && hasCost,
    costMaxUsd,
    experimentMetricRules: experimentMetricKeys.map((key) => {
      const current = summaryQuery.data?.experiment_metrics?.[key];
      return {
        key,
        enabled: runMetricEdits[key]?.enabled ?? false,
        bound:
          runMetricEdits[key]?.bound ??
          (typeof current === "number" ? String(current) : ""),
      };
    }),
    groupsEnabled: groupsEnabled && groupKeys.length > 0,
    groupsBy,
    groupsMinItems,
    groupsMaxDeltaPoints,
  };

  const groupsAllowed =
    bar.rules.some((r) => r.enabled) || bar.regressionEnabled;
  const generatedPolicy = policyFromQualityBar({
    ...bar,
    groupsEnabled: bar.groupsEnabled && groupsAllowed,
  });
  const generatedYaml = dump(generatedPolicy, { lineWidth: 100 });

  function editRule(name: string, patch: { enabled?: boolean; min?: string }) {
    setRuleEdits((prev) => ({ ...prev, [name]: { ...prev[name], ...patch } }));
  }

  function editRunMetric(key: string, patch: { enabled?: boolean; bound?: string }) {
    setRunMetricEdits((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }));
  }

  function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    setParseError(null);
    let policy: Record<string, unknown> = generatedPolicy;
    if (yamlMode) {
      try {
        policy = parsePolicyYaml(yamlDraft);
      } catch (err) {
        setParseError(err instanceof Error ? err.message : "Invalid YAML");
        releaseCheck.reset();
        return;
      }
    }
    if (Object.keys(policy).length === 0) {
      setParseError("Turn on at least one rule.");
      return;
    }
    releaseCheck.mutate({
      experiment_id: experimentId,
      baseline_experiment_id: baselineId,
      policy,
    });
  }

  async function copyYaml() {
    try {
      await navigator.clipboard.writeText(yamlMode ? yamlDraft : generatedYaml);
      toast.success("Rules copied — paste them into opengrade.yaml for CI");
    } catch {
      toast.error("Could not copy");
    }
  }

  if (experimentsQuery.isLoading) {
    return <LoadingBlock className="min-h-[240px]" />;
  }

  if (experimentsQuery.isError) {
    return (
      <ErrorState
        title="Could not load experiments"
        message={formatErrorForUi(experimentsQuery.error)}
        onRetry={() => void experimentsQuery.refetch()}
      />
    );
  }

  if (experiments.length === 0) {
    return (
      <EmptyState
        title="No experiments yet"
        description="Run and score an experiment first. The quality gate then checks it against your quality bar."
        action={
          <Link
            href={withProjectQuery("/experiments", projectId)}
            className={cn(buttonVariants({ variant: "default", size: "sm" }))}
          >
            Go to Experiments
          </Link>
        }
      />
    );
  }

  const scored =
    (summaryQuery.data?.evaluators.length ?? 0) > 0 ||
    Object.keys(summaryQuery.data?.experiment_metrics ?? {}).length > 0;

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Step
          n={1}
          title="Choose what to check"
          description="The candidate is the new version. The baseline is the reference you compare against."
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="release-experiment" id="release-experiment-label" className="text-xs font-medium text-muted-foreground">
                Candidate experiment
              </label>
              <Select
                value={experimentId}
                onValueChange={(v) => {
                  setExperimentId(v ?? "");
                  setBaselinePick(null);
                  setRuleEdits({});
                  setRunMetricEdits({});
                  setCostEnabled(false);
                  setCostMaxUsd(null);
                  setGroupsEnabled(false);
                  setGroupsBy(null);
                  setGroupsMinItems(DEFAULT_GROUPS_MIN_ITEMS);
                  setGroupsMaxDeltaPoints("");
                  releaseCheck.reset();
                }}
              >
                <SelectTrigger id="release-experiment" className="w-full">
                  <SelectValue placeholder="Choose an experiment" />
                </SelectTrigger>
                <SelectContent>
                  {experiments.map((exp) => (
                    <SelectItem key={exp.id} value={exp.id}>
                      {exp.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="release-baseline" id="release-baseline-label" className="text-xs font-medium text-muted-foreground">
                Baseline
              </label>
              <Select
                value={baselineId ?? NO_BASELINE}
                onValueChange={(v) => setBaselinePick(v ?? NO_BASELINE)}
                disabled={!experimentId}
              >
                <SelectTrigger id="release-baseline" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_BASELINE}>No baseline</SelectItem>
                  {experiments
                    .filter(
                      (exp) =>
                        exp.id !== experimentId &&
                        (!selectedExperiment || exp.dataset_id === selectedExperiment.dataset_id),
                    )
                    .map((exp) => (
                      <SelectItem key={exp.id} value={exp.id}>
                        {exp.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </Step>

        <Step
          n={2}
          title="Set your quality bar"
          description="The gate passes only if every rule below is met. Defaults come from your project metrics."
        >
          {!experimentId ? (
            <p className="text-sm text-muted-foreground">Choose a candidate experiment first.</p>
          ) : summaryQuery.isLoading ? (
            <LoadingBlock className="min-h-[120px]" />
          ) : !scored ? (
            <p className="text-sm text-muted-foreground">
              This experiment has not been scored yet.{" "}
              <Link
                href={withProjectQuery(`/experiments/${encodeURIComponent(experimentId)}`, projectId)}
                className="text-primary hover:underline"
              >
                Score it first
              </Link>
              .
            </p>
          ) : yamlMode ? (
            <div className="flex flex-col gap-1.5">
              <label htmlFor="release-policy" id="release-policy-label" className="text-xs font-medium text-muted-foreground">
                Rules (YAML)
              </label>
              <Textarea
                id="release-policy"
                value={yamlDraft}
                onChange={(e) => {
                  setYamlDraft(e.target.value);
                  if (parseError) setParseError(null);
                }}
                rows={12}
                className="font-mono text-xs"
                spellCheck={false}
              />
            </div>
          ) : (
            <div className="flex flex-col divide-y divide-border rounded-md border border-border">
              {bar.rules.map((rule) => {
                const info = metricInfo(rule.name);
                return (
                  <label
                    key={rule.name}
                    className="flex items-center gap-3 px-3 py-2 text-sm"
                    title={info.description}
                  >
                    <input
                      type="checkbox"
                      className="size-4 accent-primary"
                      checked={rule.enabled}
                      onChange={(e) => editRule(rule.name, { enabled: e.target.checked })}
                    />
                    <span className={cn("flex-1", !rule.enabled && "text-muted-foreground")}>
                      {info.label} average score at least
                    </span>
                    <Input
                      type="number"
                      step="0.05"
                      min={0}
                      max={1}
                      value={rule.min}
                      disabled={!rule.enabled}
                      onChange={(e) => editRule(rule.name, { min: e.target.value })}
                      className="h-8 w-20 tabular-nums"
                      aria-label={`Minimum ${info.label}`}
                    />
                  </label>
                );
              })}
              {hasLatency ? (
                <label className="flex items-center gap-3 px-3 py-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4 accent-primary"
                    checked={latencyEnabled}
                    onChange={(e) => setLatencyEnabled(e.target.checked)}
                  />
                  <span className={cn("flex-1", !latencyEnabled && "text-muted-foreground")}>
                    95% of answers arrive within (seconds)
                  </span>
                  <Input
                    type="number"
                    step="0.5"
                    min={0}
                    value={latencySeconds}
                    disabled={!latencyEnabled}
                    onChange={(e) => setLatencySeconds(e.target.value)}
                    className="h-8 w-20 tabular-nums"
                    aria-label="Latency budget in seconds"
                  />
                </label>
              ) : null}
              {hasCost ? (
                <label className="flex items-center gap-3 px-3 py-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4 accent-primary"
                    checked={costEnabled}
                    onChange={(e) => setCostEnabled(e.target.checked)}
                  />
                  <span className={cn("flex-1", !costEnabled && "text-muted-foreground")}>
                    Average cost per answer at most (USD)
                  </span>
                  <Input
                    type="number"
                    step="0.001"
                    min={0}
                    value={costMaxUsd}
                    disabled={!costEnabled}
                    onChange={(e) => setCostMaxUsd(e.target.value)}
                    className="h-8 w-24 tabular-nums"
                    aria-label="Maximum average cost per answer in USD"
                  />
                </label>
              ) : null}
              <label
                className="flex items-center gap-3 px-3 py-2 text-sm"
                title={baselineId ? undefined : "Choose a baseline to enable this rule"}
              >
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  checked={regressionEnabled && baselineId != null}
                  disabled={baselineId == null}
                  onChange={(e) => setRegressionEnabled(e.target.checked)}
                />
                <span
                  className={cn(
                    "flex-1",
                    (!regressionEnabled || baselineId == null) && "text-muted-foreground",
                  )}
                >
                  No significant drop vs baseline (95% CI); optional mean floor (points)
                </span>
                <Input
                  type="number"
                  step="1"
                  min={0}
                  value={regressionPoints}
                  disabled={!regressionEnabled || baselineId == null}
                  onChange={(e) => setRegressionPoints(e.target.value)}
                  className="h-8 w-20 tabular-nums"
                  placeholder="—"
                  aria-label="Optional mean-score floor in points"
                />
              </label>
              {experimentMetricKeys.map((key) => {
                const rule = bar.experimentMetricRules.find((r) => r.key === key)!;
                const lower = isLowerBetter(key);
                return (
                  <label
                    key={key}
                    className="flex items-center gap-3 px-3 py-2 text-sm"
                    title="Experiment-level scalar from log_metrics"
                  >
                    <input
                      type="checkbox"
                      className="size-4 accent-primary"
                      checked={rule.enabled}
                      onChange={(e) => editRunMetric(key, { enabled: e.target.checked })}
                    />
                    <span className={cn("flex-1", !rule.enabled && "text-muted-foreground")}>
                      Run metric {key} {lower ? "at most" : "at least"}
                    </span>
                    <Input
                      type="number"
                      step="any"
                      value={rule.bound}
                      disabled={!rule.enabled}
                      onChange={(e) => editRunMetric(key, { bound: e.target.value })}
                      className="h-8 w-24 tabular-nums"
                      aria-label={`${lower ? "Maximum" : "Minimum"} ${key}`}
                    />
                  </label>
                );
              })}
              {groupKeys.length > 0 ? (
                <div className="flex flex-col gap-2 px-3 py-2 text-sm">
                  <label
                    className="flex items-center gap-3"
                    title={
                      groupsAllowed
                        ? "Re-apply metric mins (and regression) inside each metadata slice"
                        : "Enable at least one metric min or regression first"
                    }
                  >
                    <input
                      type="checkbox"
                      className="size-4 accent-primary"
                      checked={groupsEnabled && groupsAllowed}
                      disabled={!groupsAllowed}
                      onChange={(e) => setGroupsEnabled(e.target.checked)}
                    />
                    <span
                      className={cn(
                        "flex-1",
                        (!groupsEnabled || !groupsAllowed) && "text-muted-foreground",
                      )}
                    >
                      Also gate by metadata group
                    </span>
                  </label>
                  {groupsEnabled && groupsAllowed ? (
                    <div className="flex flex-wrap items-end gap-3 pl-7">
                      <div className="flex min-w-[8rem] flex-1 flex-col gap-1">
                        <span className="text-xs text-muted-foreground">Field</span>
                        <Select value={groupsBy} onValueChange={(v) => setGroupsBy(v ?? "")}>
                          <SelectTrigger className="h-8 w-full" aria-label="Group metadata field">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {groupKeys.map((key) => (
                              <SelectItem key={key} value={key}>
                                {key}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="flex w-20 flex-col gap-1">
                        <span className="text-xs text-muted-foreground">Min items</span>
                        <Input
                          type="number"
                          step="1"
                          min={1}
                          value={groupsMinItems}
                          onChange={(e) => setGroupsMinItems(e.target.value)}
                          className="h-8 tabular-nums"
                          aria-label="Minimum items per group"
                        />
                      </div>
                      <div className="flex w-24 flex-col gap-1">
                        <span className="text-xs text-muted-foreground">Floor (pts)</span>
                        <Input
                          type="number"
                          step="1"
                          min={0}
                          value={groupsMaxDeltaPoints}
                          onChange={(e) => setGroupsMaxDeltaPoints(e.target.value)}
                          className="h-8 tabular-nums"
                          placeholder="—"
                          aria-label="Optional group regression floor in points"
                        />
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          )}
          {scored ? (
            <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
              <button
                type="button"
                className="text-primary hover:underline"
                onClick={() => {
                  if (!yamlMode) setYamlDraft(generatedYaml);
                  setYamlMode((m) => !m);
                  setParseError(null);
                }}
              >
                {yamlMode ? "Back to the form" : "Edit as YAML"}
              </button>
              <button
                type="button"
                className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
                onClick={copyYaml}
              >
                <Copy className="size-3" />
                Copy rules for CI
              </button>
            </div>
          ) : null}
          {parseError ? (
            <p className="mt-2 text-sm text-status-fail" role="alert">
              {parseError}
            </p>
          ) : null}
        </Step>

        <Button
          type="submit"
          className="self-start"
          disabled={releaseCheck.isPending || !experimentId || !scored}
        >
          <ShieldCheck className="size-4" />
          {releaseCheck.isPending ? "Checking…" : "Run quality gate"}
        </Button>
      </form>

      <div className="flex flex-col gap-4">
        {releaseCheck.isError ? (
          <ErrorState
            title="Quality gate failed"
            message={formatErrorForUi(releaseCheck.error)}
            onRetry={() => releaseCheck.reset()}
          />
        ) : null}
        {releaseCheck.data && !releaseCheck.isPending && !releaseCheck.isError ? (
          <ReleaseResult
            projectId={projectId}
            result={releaseCheck.data}
            experimentName={
              experiments.find((e) => e.id === releaseCheck.data.experiment_id)?.name
            }
            baselineName={
              releaseCheck.data.baseline_experiment_id
                ? experiments.find(
                    (e) => e.id === releaseCheck.data.baseline_experiment_id,
                  )?.name
                : null
            }
          />
        ) : (
          <div className="flex min-h-[200px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-surface p-6 text-center">
            <ShieldCheck className="size-6 text-muted-foreground" />
            <p className="text-sm font-medium text-foreground">The verdict appears here</p>
            <p className="max-w-sm text-sm text-muted-foreground">
              You get a clear “ready to ship” or “not ready”, with every rule that
              failed and a link to the answers that caused it.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
