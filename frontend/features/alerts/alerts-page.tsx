"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BellRing, Pencil, Plus, Send, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { ProductionHeader } from "@/components/production-header";
import { RelativeTime } from "@/components/relative-time";
import { Button } from "@/components/ui/button";
import { useMonitoring, useReleaseFacets } from "@/features/monitoring/use-monitoring";
import {
  deleteAlertRule,
  evaluateAlertRules,
  testAlertRule,
  updateAlertRule,
} from "@/lib/api/alerts";
import { formatErrorForUi } from "@/lib/api/client";
import type { AlertEvent, AlertRule } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { describeRule, formatAlertValue } from "./alert-format";
import { AlertRuleDialog, type ScoreChoice } from "./alert-rule-dialog";
import {
  alertEventsQueryKey,
  alertRulesQueryKey,
  useAlertEvents,
  useAlertRules,
} from "./use-alerts";

const STATE_STYLES: Record<AlertRule["state"], string> = {
  firing: "bg-status-fail-bg text-status-fail",
  ok: "bg-status-ok-bg text-status-ok",
  no_data: "bg-status-unset-bg text-status-unset",
};

const STATE_LABELS: Record<AlertRule["state"], string> = {
  firing: "Firing",
  ok: "OK",
  no_data: "No data",
};

const EVENT_LABELS: Record<AlertEvent["kind"], string> = {
  firing: "Fired",
  resolved: "Resolved",
  repeat: "Reminder",
  test: "Test",
};

function useRecentScores(projectId: string): {
  scores: ScoreChoice[];
  environments: string[];
  versions: string[];
} {
  // Anchor once per mount: score names for the dialog do not need a moving window.
  const [range] = useState(() => {
    const until = new Date();
    return {
      since: new Date(until.getTime() - 7 * 24 * 3600 * 1000).toISOString(),
      until: until.toISOString(),
    };
  });
  const monitoring = useMonitoring(projectId, range.since, range.until);
  const facets = useReleaseFacets(projectId, range.since, range.until);
  const scores = useMemo(
    () => (monitoring.data?.metrics ?? []).map((m) => ({ name: m.name, source: m.source })),
    [monitoring.data],
  );
  return {
    scores,
    environments: (facets.data?.environments ?? []).map((f) => f.value),
    versions: (facets.data?.versions ?? []).map((f) => f.value),
  };
}

export function AlertsPage({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const rules = useAlertRules(projectId);
  const events = useAlertEvents(projectId);
  const recent = useRecentScores(projectId);
  const [editing, setEditing] = useState<AlertRule | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: alertRulesQueryKey(projectId) }),
      queryClient.invalidateQueries({ queryKey: alertEventsQueryKey(projectId) }),
    ]);
  }

  const checkNow = useMutation({
    mutationFn: () => evaluateAlertRules(projectId),
    onSuccess: async (results) => {
      await refresh();
      const fired = results.filter((r) => r.event).length;
      toast.success(
        fired ? `Checked: ${fired} notification${fired === 1 ? "" : "s"} sent` : "Checked: no change",
      );
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  function openDialog(rule: AlertRule | null) {
    setEditing(rule);
    setDialogOpen(true);
  }

  return (
    <div className="flex flex-col gap-4">
      <ProductionHeader
        active="alerts"
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => checkNow.mutate()}
              disabled={checkNow.isPending || !rules.data?.length}
            >
              {checkNow.isPending ? "Checking…" : "Check now"}
            </Button>
            <Button size="sm" onClick={() => openDialog(null)}>
              <Plus className="size-4" aria-hidden />
              New alert
            </Button>
          </>
        }
      />
      {rules.isLoading ? (
        <LoadingBlock className="min-h-[200px]" />
      ) : rules.isError ? (
        <ErrorState
          title="Could not load alerts"
          message={formatErrorForUi(rules.error)}
          onRetry={() => void rules.refetch()}
        />
      ) : !rules.data?.length ? (
        <EmptyState
          title="No alerts yet"
          description="Get a Slack or webhook message when a production score, the error rate, latency or cost crosses a threshold. The server checks every minute."
          action={
            <Button size="sm" onClick={() => openDialog(null)}>
              New alert
            </Button>
          }
        />
      ) : (
        <ul className="flex flex-col gap-2" aria-label="Alert rules">
          {rules.data.map((rule) => (
            <RuleRow
              key={rule.id}
              rule={rule}
              onEdit={() => openDialog(rule)}
              onChanged={refresh}
            />
          ))}
        </ul>
      )}

      <section aria-labelledby="alert-events-title" className="flex flex-col gap-2">
        <h2 id="alert-events-title" className="text-sm font-semibold text-foreground">
          Recent notifications
        </h2>
        {events.data?.length ? (
          <ul className="flex flex-col divide-y divide-border rounded-lg border border-border bg-surface">
            {events.data.map((event) => (
              <li key={event.id} className="flex flex-wrap items-start gap-x-3 gap-y-1 px-3 py-2 text-sm">
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-xs font-medium",
                    event.kind === "resolved"
                      ? "bg-status-ok-bg text-status-ok"
                      : event.kind === "test"
                        ? "bg-status-unset-bg text-status-unset"
                        : "bg-status-fail-bg text-status-fail",
                  )}
                >
                  {EVENT_LABELS[event.kind]}
                </span>
                <span className="min-w-0 flex-1 break-words text-foreground">{event.message}</span>
                <span
                  className={cn(
                    "text-xs",
                    event.delivery_status === "failed" ? "text-status-fail" : "text-muted-foreground",
                  )}
                  title={event.delivery_error ?? undefined}
                >
                  {event.delivery_status === "sent"
                    ? "delivered"
                    : event.delivery_status === "failed"
                      ? "delivery failed"
                      : "no webhook"}
                  {" · "}
                  <RelativeTime date={event.created_at} />
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Nothing has fired yet.</p>
        )}
      </section>

      <AlertRuleDialog
        projectId={projectId}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        rule={editing}
        scores={recent.scores}
        environments={recent.environments}
        versions={recent.versions}
      />
    </div>
  );
}

function RuleRow({
  rule,
  onEdit,
  onChanged,
}: {
  rule: AlertRule;
  onEdit: () => void;
  onChanged: () => Promise<void>;
}) {
  const toggle = useMutation({
    mutationFn: () => updateAlertRule(rule.id, { enabled: !rule.enabled }),
    onSuccess: onChanged,
    onError: (err) => toast.error(formatErrorForUi(err)),
  });
  const test = useMutation({
    mutationFn: () => testAlertRule(rule.id),
    onSuccess: async (event) => {
      await onChanged();
      if (event.delivery_status === "sent") toast.success("Test notification delivered");
      else if (event.delivery_status === "failed")
        toast.error(`Delivery failed: ${event.delivery_error ?? "unknown error"}`);
      else toast.message("No webhook configured: the test was only logged");
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });
  const remove = useMutation({
    mutationFn: () => deleteAlertRule(rule.id),
    onSuccess: async () => {
      await onChanged();
      toast.success("Alert deleted");
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  return (
    <li
      className={cn(
        "flex flex-wrap items-center gap-3 rounded-lg border bg-surface px-4 py-3",
        rule.enabled && rule.state === "firing" ? "border-status-fail" : "border-border",
        !rule.enabled && "opacity-60",
      )}
    >
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium",
          rule.enabled ? STATE_STYLES[rule.state] : "bg-status-unset-bg text-status-unset",
        )}
      >
        {rule.enabled && rule.state === "firing" ? <BellRing className="size-3" aria-hidden /> : null}
        {rule.enabled ? STATE_LABELS[rule.state] : "Paused"}
      </span>
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="text-sm font-medium text-foreground">{rule.name}</span>
        <span className="text-xs text-muted-foreground">
          {describeRule(rule)}
          {rule.last_evaluated_at ? (
            <>
              {" · now "}
              {formatAlertValue(rule.metric, rule.last_value)}
              {" · checked "}
              <RelativeTime date={rule.last_evaluated_at} />
            </>
          ) : null}
          {rule.webhook_url ? "" : " · server default webhook"}
        </span>
      </div>
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="sm" onClick={() => toggle.mutate()} disabled={toggle.isPending}>
          {rule.enabled ? "Pause" : "Resume"}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => test.mutate()}
          disabled={test.isPending}
          title="Send a test notification"
        >
          <Send className="size-4" aria-hidden />
          <span className="sr-only">Send test</span>
        </Button>
        <Button variant="ghost" size="sm" onClick={onEdit} title="Edit">
          <Pencil className="size-4" aria-hidden />
          <span className="sr-only">Edit</span>
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            if (window.confirm(`Delete alert "${rule.name}"?`)) remove.mutate();
          }}
          disabled={remove.isPending}
          title="Delete"
        >
          <Trash2 className="size-4" aria-hidden />
          <span className="sr-only">Delete</span>
        </Button>
      </div>
    </li>
  );
}
