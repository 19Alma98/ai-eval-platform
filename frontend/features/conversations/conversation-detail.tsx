"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { MetaItem, PageHeader } from "@/components/page-header";
import { ProductionHeader } from "@/components/production-header";
import { RelativeTime } from "@/components/relative-time";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatErrorForUi } from "@/lib/api/client";
import {
  getConversation,
  scoreConversation,
} from "@/lib/api/conversations";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { metricLabel } from "@/lib/metrics-catalog";
import { useCanWrite } from "@/lib/auth-context";

export function ConversationDetail({ sessionId }: { sessionId: string }) {
  const { projectId } = useProjectId();
  const writable = useCanWrite();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["conversation", projectId, sessionId],
    queryFn: () => getConversation(projectId!, sessionId),
    enabled: Boolean(projectId && sessionId),
  });

  const scoreMutation = useMutation({
    mutationFn: () => scoreConversation(projectId!, sessionId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["conversation", projectId, sessionId],
      });
      toast.success("Session judges finished");
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  if (!projectId || query.isPending) return <LoadingBlock className="min-h-[240px]" />;
  if (query.isError || !query.data) {
    return (
      <ErrorState
        title="Could not load conversation"
        message={formatErrorForUi(query.error)}
        onRetry={() => query.refetch()}
      />
    );
  }

  const detail = query.data;
  const listHref = withProjectQuery("/conversations", projectId);

  return (
    <div className="flex flex-col gap-4">
      <ProductionHeader
        active="conversations"
        actions={
          writable ? (
            <Button
              size="sm"
              onClick={() => scoreMutation.mutate()}
              disabled={scoreMutation.isPending}
            >
              {scoreMutation.isPending ? "Scoring…" : "Run session judges"}
            </Button>
          ) : null
        }
      />
      <PageHeader
        title={detail.summary.session_id}
        description="Chat timeline for this session. Per-turn scores live on Live answers; session judges score the whole conversation."
        breadcrumbs={[
          { label: "Production", href: listHref },
          { label: "Conversations", href: listHref },
          { label: detail.summary.session_id },
        ]}
        meta={
          <>
            <MetaItem label="Turns">{String(detail.summary.turn_count)}</MetaItem>
            <MetaItem label="Last activity">
              <RelativeTime date={detail.summary.last_activity_at} />
            </MetaItem>
            <MetaItem label="Judge">
              {detail.judge_status ?? detail.summary.judge_status ?? "—"}
            </MetaItem>
          </>
        }
      />

      {detail.scores.length > 0 ? (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-medium">Session scores</h2>
          <ul className="flex flex-col gap-2">
            {detail.scores.map((score) => (
              <li
                key={score.id}
                className="rounded-md border border-border bg-surface px-3 py-2 text-sm"
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium">{metricLabel(score.kind)}</span>
                  {score.label ? <Badge variant="secondary">{score.label}</Badge> : null}
                  {score.score != null ? (
                    <span className="tabular-nums text-muted-foreground">
                      {score.score.toFixed(2)}
                    </span>
                  ) : null}
                </div>
                {score.explanation ? (
                  <p className="mt-1 text-muted-foreground">{score.explanation}</p>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium">Timeline</h2>
        <ol className="flex flex-col gap-3">
          {detail.turns.map((turn) => (
            <li
              key={turn.trace_id}
              className="rounded-md border border-border bg-surface px-3 py-3 text-sm"
            >
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <RelativeTime date={turn.start_time} />
                <Link
                  href={withProjectQuery(`/traces/${turn.trace_id}`, projectId)}
                  className="text-primary hover:underline"
                >
                  Trace
                </Link>
                {turn.live_interaction_id ? (
                  <Link
                    href={withProjectQuery(
                      `/live-runs/${turn.live_interaction_id}`,
                      projectId,
                    )}
                    className="text-primary hover:underline"
                  >
                    Live answer
                  </Link>
                ) : null}
                {turn.search_query ? (
                  <span className="font-mono">query: {turn.search_query}</span>
                ) : null}
              </div>
              {turn.question ? (
                <p>
                  <span className="font-medium text-muted-foreground">User · </span>
                  {turn.question}
                </p>
              ) : null}
              {turn.answer ? (
                <p className="mt-1">
                  <span className="font-medium text-muted-foreground">Assistant · </span>
                  {turn.answer}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
