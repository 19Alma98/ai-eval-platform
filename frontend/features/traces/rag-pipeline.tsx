"use client";

import { useMemo, useState } from "react";
import { ArrowDown } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  parseJudgeClaims,
  verdictTone,
  type JudgeClaim,
  type VerdictTone,
} from "@/features/judges/judge-metadata";
import type { LiveInteraction } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatScore } from "@/lib/format";
import { metricLabel } from "@/lib/metrics-catalog";
import {
  claimsForChunk,
  highlightQuotes,
  type RagChunk,
  type RagView,
} from "./rag-view";

const TONE_TEXT: Record<VerdictTone, string> = {
  ok: "bg-status-ok-bg text-status-ok",
  warn: "bg-status-warn-bg text-status-warn",
  fail: "bg-status-fail-bg text-status-fail",
};

const TONE_MARK: Record<VerdictTone, string> = {
  ok: "bg-status-ok-bg text-foreground",
  warn: "bg-status-warn-bg text-foreground",
  fail: "bg-status-fail-bg text-foreground",
};

type LabeledClaim = JudgeClaim & { metric: string };

/** Claims the live judge extracted from the answer, across all its metrics. */
export function claimsFromInteraction(interaction: LiveInteraction | undefined): LabeledClaim[] {
  if (!interaction) return [];
  return interaction.scores.flatMap((score) =>
    (parseJudgeClaims(score.metadata) ?? []).map((claim) => ({
      ...claim,
      metric: score.kind,
    })),
  );
}

function Step({
  title,
  hint,
  children,
  last = false,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
  last?: boolean;
}) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {title}
        </h2>
        {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
      </div>
      {children}
      {last ? null : (
        <ArrowDown className="mx-auto size-4 text-muted-foreground" aria-hidden />
      )}
    </section>
  );
}

function ScoreBar({ score, max }: { score: number | null; max: number }) {
  if (score == null) return null;
  const pct = max > 0 ? Math.max(0, Math.min(1, score / max)) * 100 : 0;
  return (
    <span className="flex items-center gap-1.5" title={`Retrieval score ${score}`}>
      <span className="h-1.5 w-16 overflow-hidden rounded bg-surface-2">
        <span className="block h-full rounded bg-primary" style={{ width: `${pct}%` }} />
      </span>
      <span className="text-xs tabular-nums text-muted-foreground">{formatScore(score)}</span>
    </span>
  );
}

function ChunkCard({
  chunk,
  rank,
  maxScore,
  claims,
  activeClaim,
}: {
  chunk: RagChunk;
  rank: number;
  maxScore: number;
  claims: LabeledClaim[];
  activeClaim: number | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const linked = claimsForChunk(chunk, claims);
  const isActive = activeClaim != null && linked.includes(activeClaim);
  const parts = chunk.text ? highlightQuotes(chunk.text, claims) : [];

  return (
    <li
      className={cn(
        "rounded-md border border-border bg-surface px-3 py-2 text-sm transition-colors",
        isActive && "border-primary ring-1 ring-primary",
        activeClaim != null && !isActive && "opacity-60",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs tabular-nums text-muted-foreground">#{rank}</span>
        <span className="font-medium text-foreground">{chunk.title ?? chunk.id}</span>
        {chunk.title ? (
          <Badge variant="outline" className="font-normal">
            {chunk.id}
          </Badge>
        ) : null}
        <span className="flex-1" />
        {linked.length > 0 ? (
          <span className="text-xs text-muted-foreground">
            used by {linked.length} claim{linked.length === 1 ? "" : "s"}
          </span>
        ) : null}
        <ScoreBar score={chunk.score} max={maxScore} />
      </div>
      {chunk.text ? (
        <p
          className={cn(
            "mt-1 whitespace-pre-wrap text-muted-foreground",
            !expanded && "line-clamp-4",
          )}
        >
          {parts.map((part, i) =>
            part.claimIndexes.length > 0 ? (
              <mark
                key={i}
                className={cn(
                  "rounded px-0.5",
                  TONE_MARK[verdictTone(claims[part.claimIndexes[0]].verdict)],
                  activeClaim != null &&
                    part.claimIndexes.includes(activeClaim) &&
                    "ring-1 ring-primary",
                )}
              >
                {part.text}
              </mark>
            ) : (
              <span key={i}>{part.text}</span>
            ),
          )}
        </p>
      ) : (
        <p className="mt-1 text-xs text-muted-foreground">Text was not captured.</p>
      )}
      {chunk.text && chunk.text.length > 280 ? (
        <button
          type="button"
          className="mt-1 text-xs text-primary hover:underline"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Show less" : "Show all"}
        </button>
      ) : null}
    </li>
  );
}

export function RagPipeline({
  view,
  interaction,
  onOpenSpan,
}: {
  view: RagView;
  interaction?: LiveInteraction;
  onOpenSpan?: (spanId: string) => void;
}) {
  const claims = useMemo(() => claimsFromInteraction(interaction), [interaction]);
  const [activeClaim, setActiveClaim] = useState<number | null>(null);
  const [stageIndex, setStageIndex] = useState<number | null>(null);
  // The last retrieval stage holds the chunks the model actually saw.
  const shownStage = stageIndex ?? view.stages.length - 1;
  const stage = view.stages[shownStage];
  const maxScore = Math.max(0, ...(stage?.chunks.map((c) => c.score ?? 0) ?? []));

  return (
    <div className="flex flex-col gap-3">
      <Step title="Query">
        <p className="rounded-md border border-border bg-surface px-3 py-2 text-sm whitespace-pre-wrap">
          {view.query ?? <span className="text-muted-foreground">Not captured</span>}
        </p>
      </Step>

      <Step
        title="Retrieved chunks"
        hint={stage ? `${stage.chunks.length} from ${stage.name}` : undefined}
      >
        {view.stages.length > 1 ? (
          <div role="radiogroup" aria-label="Retrieval stage" className="flex flex-wrap gap-1">
            {view.stages.map((s, i) => (
              <button
                key={s.spanId}
                type="button"
                role="radio"
                aria-checked={i === shownStage}
                onClick={() => setStageIndex(i)}
                className={cn(
                  "rounded border border-border px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground",
                  i === shownStage && "bg-row-selected text-foreground",
                )}
              >
                {s.kind === "RERANKER" ? "Reranked" : "Retrieved"} · {s.name}
              </button>
            ))}
          </div>
        ) : null}
        {!stage ? (
          <p className="text-sm text-muted-foreground">No retrieval step was recorded.</p>
        ) : stage.chunks.length === 0 ? (
          <p className="text-sm text-status-warn">The retriever returned no chunks.</p>
        ) : (
          <ol className="flex flex-col gap-1.5">
            {stage.chunks.map((chunk, i) => (
              <ChunkCard
                key={`${chunk.id}-${i}`}
                chunk={chunk}
                rank={i + 1}
                maxScore={maxScore}
                claims={claims}
                activeClaim={activeClaim}
              />
            ))}
          </ol>
        )}
      </Step>

      <Step title="Prompt" hint={view.prompt.length ? `${view.prompt.length} messages` : undefined}>
        {view.prompt.length === 0 ? (
          <p className="text-sm text-muted-foreground">No LLM call was recorded.</p>
        ) : (
          <details className="rounded-md border border-border bg-surface px-3 py-2 text-sm">
            <summary className="cursor-pointer text-muted-foreground">
              Show what the model received
              {view.promptSpanId && onOpenSpan ? (
                <button
                  type="button"
                  className="ml-2 text-xs text-primary hover:underline"
                  onClick={(e) => {
                    e.preventDefault();
                    onOpenSpan(view.promptSpanId!);
                  }}
                >
                  Open LLM step
                </button>
              ) : null}
            </summary>
            <div className="mt-2 flex flex-col gap-2">
              {view.prompt.map((m, i) => (
                <div key={i} className="flex flex-col gap-0.5">
                  <span className="text-xs font-medium uppercase text-muted-foreground">
                    {m.role}
                  </span>
                  <p className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-surface-2 px-2 py-1 font-mono text-xs">
                    {m.content}
                  </p>
                </div>
              ))}
            </div>
          </details>
        )}
      </Step>

      <Step title="Answer" last={claims.length === 0}>
        <p className="rounded-md border border-border bg-surface px-3 py-2 text-sm whitespace-pre-wrap">
          {view.answer ?? <span className="text-muted-foreground">Not captured</span>}
        </p>
      </Step>

      {claims.length > 0 ? (
        <Step title="Judge claims" hint="Hover a claim to see its evidence in the chunks" last>
          <ul className="flex flex-col gap-1">
            {claims.map((claim, i) => {
              const tone = verdictTone(claim.verdict);
              return (
                <li key={i}>
                  <button
                    type="button"
                    onMouseEnter={() => setActiveClaim(i)}
                    onMouseLeave={() => setActiveClaim(null)}
                    onFocus={() => setActiveClaim(i)}
                    onBlur={() => setActiveClaim(null)}
                    className={cn(
                      "flex w-full items-start gap-2 rounded-md border border-border bg-surface px-3 py-2 text-left text-sm hover:bg-row-hover",
                      activeClaim === i && "border-primary",
                    )}
                  >
                    <span
                      className={cn(
                        "shrink-0 rounded px-1.5 py-0.5 text-xs font-medium whitespace-nowrap",
                        TONE_TEXT[tone],
                      )}
                    >
                      {claim.verdict.replaceAll("_", " ")}
                    </span>
                    <span className="flex-1 text-foreground">{claim.text}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {metricLabel(claim.metric)}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </Step>
      ) : null}
    </div>
  );
}
