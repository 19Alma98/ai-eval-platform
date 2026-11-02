"use client";

import { ArrowRight } from "lucide-react";
import type { ExperimentMetricComparison } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { runMetricChanges } from "./compare-changes";
import { paramDiff } from "./experiment-matrix";

/**
 * What differs between candidate and baseline besides quality: the configuration
 * (params / model config) and experiment-level run metrics such as cost, latency and
 * error rate, with their change and whether it is better or worse.
 */
export function CompareChangesPanel({
  candidateConfig,
  baselineConfig,
  experimentMetrics,
}: {
  candidateConfig: Record<string, unknown>;
  baselineConfig: Record<string, unknown>;
  experimentMetrics: ExperimentMetricComparison[];
}) {
  const params = paramDiff(candidateConfig, baselineConfig);
  const metrics = runMetricChanges(experimentMetrics);

  return (
    <section
      aria-label="What changed"
      className="grid gap-4 rounded-lg border border-border bg-surface px-4 py-3 lg:grid-cols-2"
    >
      <div className="flex min-w-0 flex-col gap-2">
        <h2 className="text-xs font-medium text-muted-foreground">
          Configuration changes
          {params.length > 0 ? ` (${params.length})` : ""}
        </h2>
        {params.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Same parameters as the baseline: any difference comes from the code, the data or
            run-to-run noise.
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {params.map((p) => (
              <li key={p.key} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-sm">
                <span className="font-mono text-xs text-foreground">{p.key}</span>
                <span className="truncate text-muted-foreground line-through decoration-muted-foreground/50">
                  {p.baseline ?? "not set"}
                </span>
                <ArrowRight className="size-3 shrink-0 text-muted-foreground" aria-label="changed to" />
                <span className="truncate font-medium text-foreground">{p.candidate ?? "not set"}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex min-w-0 flex-col gap-2">
        <h2 className="text-xs font-medium text-muted-foreground">Run metrics</h2>
        {metrics.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No run metrics on these experiments. <code className="text-xs">opengrade.evaluate</code>{" "}
            logs latency and error rate automatically; add cost or tokens with{" "}
            <code className="text-xs">opengrade.log_metrics</code>.
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {metrics.map((m) => (
              <div
                key={m.key}
                className="flex min-w-0 flex-col rounded-md border border-border px-2.5 py-1.5"
                title={`${m.key}: baseline ${m.baseline} → candidate ${m.candidate}${m.lowerIsBetter ? " (lower is better)" : ""}`}
              >
                <span className="truncate text-xs text-muted-foreground">
                  {m.label}
                  {m.lowerIsBetter ? " ↓" : ""}
                </span>
                <span className="text-sm font-medium tabular-nums text-foreground">{m.candidate}</span>
                <span className="flex items-baseline gap-1.5 text-xs tabular-nums">
                  <span className="text-muted-foreground">was {m.baseline}</span>
                  {m.change ? (
                    <span
                      className={cn(
                        m.tone === "better" && "text-status-ok",
                        m.tone === "worse" && "text-status-fail",
                        m.tone === "neutral" && "text-muted-foreground",
                      )}
                    >
                      {m.change}
                    </span>
                  ) : null}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
