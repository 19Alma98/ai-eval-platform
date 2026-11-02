"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type SubmitEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { createAlertRule, updateAlertRule } from "@/lib/api/alerts";
import { formatErrorForUi } from "@/lib/api/client";
import type {
  AlertCondition,
  AlertMetric,
  AlertOperator,
  AlertRule,
  AlertRuleInput,
} from "@/lib/api/types";
import {
  ALERT_METRICS,
  BASELINE_OPTIONS,
  CONDITION_OPTIONS,
  conditionDefaults,
  metricOption,
  signedThreshold,
  thresholdFromInput,
  thresholdToInput,
  WINDOW_OPTIONS,
} from "./alert-format";
import { alertRulesQueryKey } from "./use-alerts";

const ANY_SOURCE = "__any__";

export type ScoreChoice = { name: string; source: string };

type Draft = {
  name: string;
  metric: AlertMetric;
  condition: AlertCondition;
  operator: AlertOperator;
  threshold: string;
  windowMinutes: number;
  /** Change rules: comparison period; 0 = same length as the window. */
  baselineMinutes: number;
  scoreName: string;
  scoreSource: string;
  webhookUrl: string;
  webhookFormat: "json" | "slack";
  repeatMinutes: string;
  environment: string;
  version: string;
};

function draftFrom(rule: AlertRule | null, preset?: Partial<AlertRuleInput>): Draft {
  const metric = rule?.metric ?? preset?.metric ?? "score_fail_rate";
  const option = metricOption(metric);
  const condition = rule?.condition ?? preset?.condition ?? "threshold";
  const windowMinutes = rule?.window_minutes ?? preset?.window_minutes ?? 60;
  const baseline = rule?.baseline_minutes ?? null;
  return {
    name: rule?.name ?? preset?.name ?? "",
    metric,
    condition,
    operator: rule?.operator ?? preset?.operator ?? option.defaultOperator,
    threshold: thresholdToInput(
      metric,
      rule?.threshold ?? preset?.threshold ?? option.defaultThreshold,
      condition,
    ),
    windowMinutes,
    baselineMinutes: baseline == null || baseline === windowMinutes ? 0 : baseline,
    scoreName: rule?.score_name ?? preset?.score_name ?? "",
    scoreSource: rule?.score_source ?? preset?.score_source ?? ANY_SOURCE,
    webhookUrl: rule?.webhook_url ?? "",
    webhookFormat: rule?.webhook_format ?? "json",
    repeatMinutes: rule?.repeat_minutes != null ? String(rule.repeat_minutes) : "",
    environment: rule?.environment ?? preset?.environment ?? "",
    version: rule?.version ?? preset?.version ?? "",
  };
}

export function AlertRuleDialog({
  projectId,
  open,
  onOpenChange,
  rule,
  preset,
  scores,
  environments = [],
  versions = [],
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Rule to edit; null creates a new one. */
  rule: AlertRule | null;
  preset?: Partial<AlertRuleInput>;
  /** Production scores seen recently, offered for score_* metrics. */
  scores: ScoreChoice[];
  /** Environments / versions seen recently, suggested for the rule's scope. */
  environments?: string[];
  versions?: string[];
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => draftFrom(rule, preset));
  const [syncedFor, setSyncedFor] = useState<string | null>(rule?.id ?? null);
  if (open && syncedFor !== (rule?.id ?? null)) {
    setSyncedFor(rule?.id ?? null);
    setDraft(draftFrom(rule, preset));
  }
  const option = metricOption(draft.metric);
  const scoreNames = useMemo(() => [...new Set(scores.map((s) => s.name))].sort(), [scores]);
  const sources = useMemo(
    () => [...new Set(scores.filter((s) => s.name === draft.scoreName).map((s) => s.source))].sort(),
    [scores, draft.scoreName],
  );

  function set<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
  }

  function setMetric(metric: AlertMetric) {
    setDraft((d) => {
      const condition = metric === "needs_review" ? "threshold" : d.condition;
      const defaults = conditionDefaults(metric, condition);
      return {
        ...d,
        metric,
        condition,
        operator: defaults.operator,
        threshold: thresholdToInput(metric, defaults.threshold, condition),
      };
    });
  }

  function setCondition(condition: AlertCondition) {
    setDraft((d) => {
      const defaults = conditionDefaults(d.metric, condition);
      return {
        ...d,
        condition,
        operator: defaults.operator,
        threshold: thresholdToInput(d.metric, defaults.threshold, condition),
      };
    });
  }

  const save = useMutation({
    mutationFn: async () => {
      const typed = thresholdFromInput(draft.metric, draft.threshold, draft.condition);
      if (typed == null) throw new Error("Enter a number for the threshold");
      const threshold = signedThreshold(draft.condition, draft.operator, typed);
      const body: AlertRuleInput = {
        name: draft.name.trim(),
        metric: draft.metric,
        condition: draft.condition,
        // Anomaly rules use the server default (24 past windows).
        baseline_minutes:
          draft.condition === "change" && draft.baselineMinutes > 0
            ? draft.baselineMinutes
            : null,
        operator: draft.operator,
        threshold,
        window_minutes: draft.windowMinutes,
        score_name: option.needsScore ? draft.scoreName.trim() || null : null,
        score_source:
          option.needsScore && draft.scoreSource !== ANY_SOURCE ? draft.scoreSource : null,
        webhook_url: draft.webhookUrl.trim() || null,
        webhook_format: draft.webhookFormat,
        repeat_minutes: draft.repeatMinutes.trim() ? Number(draft.repeatMinutes) : null,
        environment: draft.environment.trim() || null,
        version: draft.version.trim() || null,
      };
      if (!rule) return createAlertRule(projectId, body);
      // A metric switch resets min_samples to that metric's default on the server.
      return updateAlertRule(rule.id, body);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: alertRulesQueryKey(projectId) });
      toast.success(rule ? "Alert updated" : "Alert created");
      onOpenChange(false);
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!draft.name.trim()) return;
    save.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>{rule ? "Edit alert" : "New alert"}</DialogTitle>
            <DialogDescription>
              The server checks this rule every minute on production traffic and notifies the
              webhook when it starts or stops firing.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-4">
            <Field label="Name" htmlFor="alert-name">
              <Input
                id="alert-name"
                value={draft.name}
                onChange={(e) => set("name", e.target.value)}
                placeholder="Groundedness failing"
                required
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Metric" htmlFor="alert-metric">
                <Select value={draft.metric} onValueChange={(v) => v && setMetric(v as AlertMetric)}>
                  <SelectTrigger id="alert-metric" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ALERT_METRICS.map((m) => (
                      <SelectItem key={m.value} value={m.value}>
                        {m.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Over the last" htmlFor="alert-window">
                <Select
                  value={String(draft.windowMinutes)}
                  onValueChange={(v) => v && set("windowMinutes", Number(v))}
                >
                  <SelectTrigger id="alert-window" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WINDOW_OPTIONS.map((w) => (
                      <SelectItem key={w.minutes} value={String(w.minutes)}>
                        {w.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            </div>
            <Field label="Condition" htmlFor="alert-condition">
              <Select
                value={draft.condition}
                onValueChange={(v) => v && setCondition(v as AlertCondition)}
              >
                <SelectTrigger id="alert-condition" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CONDITION_OPTIONS.filter(
                    (c) => c.value === "threshold" || draft.metric !== "needs_review",
                  ).map((c) => (
                    <SelectItem key={c.value} value={c.value}>
                      {c.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <span className="text-xs text-muted-foreground">
                {CONDITION_OPTIONS.find((c) => c.value === draft.condition)?.hint}
                {draft.condition === "anomaly"
                  ? " Compared with the 24 windows before the current one."
                  : ""}
              </span>
            </Field>
            {draft.condition === "change" ? (
              <Field label="Compared with" htmlFor="alert-baseline">
                <Select
                  value={String(draft.baselineMinutes)}
                  onValueChange={(v) => v != null && set("baselineMinutes", Number(v))}
                >
                  <SelectTrigger id="alert-baseline" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {BASELINE_OPTIONS.filter(
                      (b) => b.minutes === 0 || b.minutes >= draft.windowMinutes,
                    ).map((b) => (
                      <SelectItem key={b.minutes} value={String(b.minutes)}>
                        {b.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            ) : null}
            {option.needsScore ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Score" htmlFor="alert-score">
                  <Input
                    id="alert-score"
                    list="alert-score-names"
                    value={draft.scoreName}
                    onChange={(e) => set("scoreName", e.target.value)}
                    placeholder="groundedness"
                    required
                  />
                  <datalist id="alert-score-names">
                    {scoreNames.map((n) => (
                      <option key={n} value={n} />
                    ))}
                  </datalist>
                </Field>
                <Field label="Source" htmlFor="alert-source">
                  <Select
                    value={draft.scoreSource}
                    onValueChange={(v) => v && set("scoreSource", v)}
                  >
                    <SelectTrigger id="alert-source" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ANY_SOURCE}>Any source</SelectItem>
                      {[...new Set([...sources, "judge", "sdk", "human"])].map((s) => (
                        <SelectItem key={s} value={s}>
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
              </div>
            ) : null}
            <div className="grid gap-3 sm:grid-cols-[140px_minmax(0,1fr)]">
              <Field label="Fire when" htmlFor="alert-operator">
                <Select
                  value={draft.operator}
                  onValueChange={(v) => v && set("operator", v as AlertOperator)}
                >
                  <SelectTrigger id="alert-operator" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="gt">
                      {draft.condition === "threshold" ? "above" : "goes up"}
                    </SelectItem>
                    <SelectItem value="lt">
                      {draft.condition === "threshold" ? "below" : "goes down"}
                    </SelectItem>
                    {draft.condition !== "threshold" ? (
                      <SelectItem value="abs">either way</SelectItem>
                    ) : null}
                  </SelectContent>
                </Select>
              </Field>
              <Field
                label={
                  draft.condition === "change"
                    ? "Change (%), e.g. -20 or 20"
                    : draft.condition === "anomaly"
                      ? "Standard deviations (z), e.g. 3"
                      : `Threshold${option.unit === "percent" ? " (%)" : option.unit === "ms" ? " (ms)" : option.unit === "usd" ? " ($)" : ""}`
                }
                htmlFor="alert-threshold"
              >
                <Input
                  id="alert-threshold"
                  type="number"
                  step="any"
                  value={draft.threshold}
                  onChange={(e) => set("threshold", e.target.value)}
                  required
                />
              </Field>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Environment (optional)" htmlFor="alert-environment">
                <Input
                  id="alert-environment"
                  list="alert-environments"
                  value={draft.environment}
                  onChange={(e) => set("environment", e.target.value)}
                  placeholder="All environments"
                />
                <datalist id="alert-environments">
                  {environments.map((v) => (
                    <option key={v} value={v} />
                  ))}
                </datalist>
              </Field>
              <Field label="Version (optional)" htmlFor="alert-version">
                <Input
                  id="alert-version"
                  list="alert-versions"
                  value={draft.version}
                  onChange={(e) => set("version", e.target.value)}
                  placeholder="All versions"
                />
                <datalist id="alert-versions">
                  {versions.map((v) => (
                    <option key={v} value={v} />
                  ))}
                </datalist>
              </Field>
            </div>
            <Field label="Webhook URL (optional)" htmlFor="alert-webhook">
              <Input
                id="alert-webhook"
                type="url"
                value={draft.webhookUrl}
                onChange={(e) => set("webhookUrl", e.target.value)}
                placeholder="https://hooks.slack.com/services/…"
              />
              <span className="text-xs text-muted-foreground">
                Empty uses the server default (ALERT_WEBHOOK_URL), if set. Events are always
                listed below.
              </span>
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Payload" htmlFor="alert-format">
                <Select
                  value={draft.webhookFormat}
                  onValueChange={(v) => v && set("webhookFormat", v as "json" | "slack")}
                >
                  <SelectTrigger id="alert-format" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="json">JSON (text + details)</SelectItem>
                    <SelectItem value="slack">Slack (text only)</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Remind every (minutes)" htmlFor="alert-repeat">
                <Input
                  id="alert-repeat"
                  type="number"
                  min={5}
                  value={draft.repeatMinutes}
                  onChange={(e) => set("repeatMinutes", e.target.value)}
                  placeholder="Only on change"
                />
              </Field>
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending || !draft.name.trim()}>
              {save.isPending ? "Saving…" : rule ? "Save" : "Create alert"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium">
        {label}
      </label>
      {children}
    </div>
  );
}
