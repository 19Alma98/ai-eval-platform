"use client";

import { cn } from "@/lib/cn";
import {
  parseJudgeClaims,
  verdictTone,
  type VerdictTone,
} from "@/features/judges/judge-metadata";

const VERDICT_LABELS: Record<string, string> = {
  supported: "Supported",
  not_supported: "Not in documents",
  contradicted: "Contradicted",
  covered: "Covered",
  missing: "Missing",
  relevant: "Relevant",
  not_relevant: "Not relevant",
};

function verdictLabel(verdict: string): string {
  const label = VERDICT_LABELS[verdict];
  if (label) return label;
  const spaced = verdict.replaceAll("_", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const TONE_STYLES: Record<VerdictTone, string> = {
  ok: "bg-status-ok-bg text-status-ok",
  warn: "bg-status-warn-bg text-status-warn",
  fail: "bg-status-fail-bg text-status-fail",
};

export function JudgeClaimsTable({
  metadata,
  claimsKey = "claims",
  title = "Claims",
}: {
  metadata: Record<string, unknown> | undefined;
  claimsKey?: "claims" | "answer_claims";
  title?: string;
}) {
  const claims = parseJudgeClaims(metadata, claimsKey);
  if (!claims || claims.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-left text-xs">
          <thead className="bg-surface text-muted-foreground">
            <tr>
              <th className="px-2 py-1.5 font-medium">Claim</th>
              <th className="px-2 py-1.5 font-medium">Verdict</th>
              <th className="px-2 py-1.5 font-medium">Source</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((claim, i) => (
              <tr key={i} className="border-t border-border align-top">
                <td className="px-2 py-1.5 text-foreground">
                  {claim.text}
                  {claim.reasoning ? (
                    <details className="mt-1 text-muted-foreground">
                      <summary className="cursor-pointer">Reasoning</summary>
                      <p className="mt-1 whitespace-pre-wrap">{claim.reasoning}</p>
                    </details>
                  ) : null}
                </td>
                <td className="px-2 py-1.5">
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 font-medium whitespace-nowrap",
                      TONE_STYLES[verdictTone(claim.verdict)],
                    )}
                  >
                    {verdictLabel(claim.verdict)}
                  </span>
                </td>
                <td className="px-2 py-1.5 text-muted-foreground">
                  {claim.docIds.length > 0 ? (
                    <div>{claim.docIds.join(", ")}</div>
                  ) : null}
                  {claim.quote ? <q className="italic">{claim.quote}</q> : null}
                  {claim.docIds.length === 0 && !claim.quote ? "—" : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
