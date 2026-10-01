"use client";

import Link from "next/link";
import { cn } from "@/lib/cn";
import type { ReleaseCheckResponse } from "@/lib/api/types";
import { truncateId } from "@/lib/format";

function formatValue(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return Number.isInteger(value) ? String(value) : value.toFixed(4);
}

function overallLabel(status: string): "PASS" | "FAIL" {
  return status.toLowerCase() === "passed" ? "PASS" : "FAIL";
}

type ReleaseResultProps = {
  projectId: string;
  result: ReleaseCheckResponse;
};

export function ReleaseResult({ projectId, result }: ReleaseResultProps) {
  const label = overallLabel(result.status);
  const passed = label === "PASS";

  const compareHref =
    result.baseline_experiment_id != null
      ? `/experiments/${encodeURIComponent(result.experiment_id)}/compare?${new URLSearchParams(
          {
            project: projectId,
            baseline: result.baseline_experiment_id,
          },
        ).toString()}`
      : null;

  return (
    <div className="flex flex-col gap-4 rounded-md border border-border bg-surface p-4">
      <div className="flex flex-col gap-1">
        <p
          className={cn(
            "flex items-center gap-2 text-base font-semibold",
            passed ? "text-status-ok" : "text-status-fail",
          )}
        >
          <span aria-hidden>●</span>
          {label}
        </p>
        <p className="text-sm text-muted-foreground">
          Experiment{" "}
          <span className="font-mono text-xs text-foreground">
            {truncateId(result.experiment_id, 12)}
          </span>
          {result.baseline_experiment_id ? (
            <>
              {" "}
              · Baseline{" "}
              <span className="font-mono text-xs text-foreground">
                {truncateId(result.baseline_experiment_id, 12)}
              </span>
            </>
          ) : null}
        </p>
      </div>

      <div>
        <h3 className="mb-2 text-sm font-medium text-foreground">Checks</h3>
        <ul className="flex flex-col gap-2" role="list">
          {result.checks.map((check) => {
            const failed = check.status.toLowerCase() === "failed";
            const row = (
              <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1 font-mono text-sm">
                <span className="min-w-[10rem] text-foreground">{check.metric}</span>
                <span className="text-muted-foreground">{check.status}</span>
                <span className="text-muted-foreground">
                  actual {formatValue(check.actual)}
                </span>
                <span className="text-muted-foreground">
                  threshold {formatValue(check.threshold)}
                </span>
              </span>
            );

            if (failed && compareHref) {
              return (
                <li key={check.metric}>
                  <Link
                    href={compareHref}
                    className="block rounded px-1 -mx-1 hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {row}
                  </Link>
                </li>
              );
            }

            return <li key={check.metric}>{row}</li>;
          })}
        </ul>
      </div>
    </div>
  );
}
