"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { cn } from "@/lib/cn";
import type { ReleaseCheckResponse } from "@/lib/api/types";
import { describeCheck, type CheckView } from "./describe-check";

type ReleaseResultProps = {
  projectId: string;
  result: ReleaseCheckResponse;
  experimentName?: string | null;
  baselineName?: string | null;
};

function OutcomeIcon({ outcome }: { outcome: CheckView["outcome"] }) {
  if (outcome === "passed") return <CheckCircle2 className="size-4 shrink-0 text-status-ok" aria-label="Passed" />;
  if (outcome === "failed") return <XCircle className="size-4 shrink-0 text-status-fail" aria-label="Failed" />;
  return <CircleDashed className="size-4 shrink-0 text-status-warn" aria-label="Not available" />;
}

export function ReleaseResult({
  projectId,
  result,
  experimentName,
  baselineName,
}: ReleaseResultProps) {
  const passed = result.status.toLowerCase() === "passed";
  const checks = result.checks.map(describeCheck);
  const order = { failed: 0, unavailable: 1, passed: 2 } as const;
  checks.sort((a, b) => order[a.outcome] - order[b.outcome]);
  const nFailed = checks.filter((c) => c.outcome === "failed").length;
  const nUnavailable = checks.filter((c) => c.outcome === "unavailable").length;

  const experimentHref = `/experiments/${encodeURIComponent(result.experiment_id)}?project=${encodeURIComponent(projectId)}`;
  const compareHref =
    result.baseline_experiment_id != null
      ? `/experiments/${encodeURIComponent(result.experiment_id)}/compare?${new URLSearchParams(
          { project: projectId, baseline: result.baseline_experiment_id },
        ).toString()}`
      : null;

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-surface p-5">
      <div
        className={cn(
          "flex items-start gap-3 rounded-md px-4 py-3",
          passed ? "bg-status-ok-bg" : "bg-status-fail-bg",
        )}
      >
        {passed ? (
          <CheckCircle2 className="mt-0.5 size-6 shrink-0 text-status-ok" />
        ) : (
          <XCircle className="mt-0.5 size-6 shrink-0 text-status-fail" />
        )}
        <div className="flex flex-col">
          <p
            className={cn(
              "text-lg font-semibold",
              passed ? "text-status-ok" : "text-status-fail",
            )}
          >
            {passed ? "Ready to ship" : "Not ready to ship"}
          </p>
          <p className="text-sm text-foreground">
            {passed
              ? `All ${checks.length} rules are met.`
              : [
                  nFailed > 0 ? `${nFailed} rule${nFailed === 1 ? "" : "s"} failed` : null,
                  nUnavailable > 0 ? `${nUnavailable} could not be checked` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
          </p>
        </div>
      </div>

      <p className="text-sm text-muted-foreground">
        Candidate{" "}
        <Link href={experimentHref} className="font-medium text-foreground hover:underline">
          {experimentName?.trim() || "this experiment"}
        </Link>
        {result.baseline_experiment_id ? (
          <>
            {" "}vs baseline{" "}
            <span className="font-medium text-foreground">
              {baselineName?.trim() || "an earlier experiment"}
            </span>
          </>
        ) : null}
      </p>

      <ul className="flex flex-col divide-y divide-border rounded-md border border-border" role="list">
        {checks.map((check) => {
          const href = check.isRegression && check.outcome === "failed" ? compareHref : null;
          const body = (
            <span className="flex items-center gap-3 px-3 py-2 text-sm">
              <OutcomeIcon outcome={check.outcome} />
              <span className="min-w-0 flex-1 break-words text-foreground">{check.title}</span>
              <span
                className={cn(
                  "shrink-0 tabular-nums",
                  check.outcome === "failed" ? "font-medium text-status-fail" : "text-foreground",
                )}
              >
                {check.outcome === "unavailable" && check.actual === "—" ? "Not available" : check.actual}
              </span>
              <span className="w-36 shrink-0 text-right text-xs text-muted-foreground">
                {check.target}
              </span>
              {href ? <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" /> : null}
            </span>
          );
          return (
            <li key={check.key}>
              {href ? (
                <Link href={href} className="block hover:bg-row-hover" title="See which answers got worse">
                  {body}
                </Link>
              ) : (
                body
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
