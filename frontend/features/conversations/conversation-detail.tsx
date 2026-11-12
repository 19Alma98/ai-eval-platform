"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type SubmitEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { MetaItem, PageHeader } from "@/components/page-header";
import { ProductionHeader } from "@/components/production-header";
import { RelativeTime } from "@/components/relative-time";
import { Badge } from "@/components/ui/badge";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useDatasets } from "@/features/datasets/use-datasets";
import {
  docsFromLiveInteraction,
  mergeGoldDocIds,
  PromoteExpectedDocFields,
} from "@/features/live-runs/promote-to-dataset-fields";
import { formatErrorForUi } from "@/lib/api/client";
import {
  getConversation,
  promoteConversation,
  scoreConversation,
} from "@/lib/api/conversations";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { metricLabel } from "@/lib/metrics-catalog";
import { useCanWrite } from "@/lib/auth-context";

function docsFromConversationLives(
  lives: { documents: Record<string, unknown>[] }[],
) {
  const seen = new Set<string>();
  const docs = [];
  for (const live of lives) {
    for (const d of docsFromLiveInteraction(live.documents)) {
      if (seen.has(d.id)) continue;
      seen.add(d.id);
      docs.push(d);
    }
  }
  return docs;
}

export function ConversationDetail({ sessionId }: { sessionId: string }) {
  const { projectId } = useProjectId();
  const writable = useCanWrite();
  const queryClient = useQueryClient();
  const router = useRouter();
  const datasets = useDatasets(projectId);
  const [promoteOpen, setPromoteOpen] = useState(false);
  const [datasetId, setDatasetId] = useState("");
  const [expectedOutput, setExpectedOutput] = useState("");
  const [expectedDocIds, setExpectedDocIds] = useState<string[]>([]);
  const [extraDocIds, setExtraDocIds] = useState("");

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

  const goldDocIds = mergeGoldDocIds(expectedDocIds, extraDocIds);
  const selectedDataset = (datasets.data ?? []).find((d) => d.id === datasetId);

  const promoteMutation = useMutation({
    mutationFn: () =>
      promoteConversation(projectId!, sessionId, {
        dataset_id: datasetId,
        expected_output: expectedOutput.trim(),
        expected_doc_ids: goldDocIds.length ? goldDocIds : undefined,
      }),
    onSuccess: (item) => {
      const forked = item.dataset_id !== datasetId;
      if (forked) {
        toast.success("Added to a new version of the test set");
      } else {
        toast.success("Added to the test set");
      }
      setPromoteOpen(false);
      setExpectedOutput("");
      setExpectedDocIds([]);
      setExtraDocIds("");
      if (projectId && forked) {
        router.push(withProjectQuery(`/datasets/${item.dataset_id}`, projectId));
      }
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
  const docPreview = docsFromConversationLives(detail.live_interactions);

  function onPromote(e: SubmitEvent) {
    e.preventDefault();
    if (!datasetId) {
      toast.error("Choose a test set");
      return;
    }
    if (!expectedOutput.trim()) {
      toast.error("Write the correct answer");
      return;
    }
    if (selectedDataset?.task_type === "rag_qa" && goldDocIds.length === 0) {
      toast.error("Add expected document IDs for this RAG test set");
      return;
    }
    promoteMutation.mutate();
  }

  return (
    <div className="flex flex-col gap-4">
      <ProductionHeader
        active="conversations"
        actions={
          writable ? (
            <>
              <Button
                size="sm"
                onClick={() => scoreMutation.mutate()}
                disabled={scoreMutation.isPending}
              >
                {scoreMutation.isPending ? "Scoring…" : "Run session judges"}
              </Button>
              <Dialog open={promoteOpen} onOpenChange={setPromoteOpen}>
                <DialogTrigger
                  render={
                    <Button type="button" size="sm" variant="outline">
                      <Plus className="size-4" />
                      Add to test set
                    </Button>
                  }
                />
                <DialogContent className="sm:max-w-lg">
                  <form onSubmit={onPromote}>
                    <DialogHeader>
                      <DialogTitle>Add this conversation to a test set</DialogTitle>
                      <DialogDescription>
                        Future experiments will be checked on it. Write the correct
                        answer yourself — the production answer is what is being
                        tested, so it is never copied.
                      </DialogDescription>
                    </DialogHeader>
                    <div className="flex flex-col gap-4 py-4">
                      <div className="flex flex-col gap-1.5">
                        <label
                          htmlFor="conversation-promote-dataset"
                          id="conversation-promote-dataset-label"
                          className="text-sm font-medium"
                        >
                          Test set
                        </label>
                        <Select value={datasetId} onValueChange={(v) => setDatasetId(v ?? "")}>
                          <SelectTrigger id="conversation-promote-dataset" className="w-full">
                            <SelectValue placeholder="Choose a test set" />
                          </SelectTrigger>
                          <SelectContent>
                            {(datasets.data ?? []).map((ds) => (
                              <SelectItem key={ds.id} value={ds.id}>
                                {ds.name} · v{ds.version}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="flex flex-col gap-1.5">
                        <label
                          htmlFor="conversation-promote-expected"
                          id="conversation-promote-expected-label"
                          className="text-sm font-medium"
                        >
                          Correct answer
                        </label>
                        <Textarea
                          id="conversation-promote-expected"
                          value={expectedOutput}
                          onChange={(e) => setExpectedOutput(e.target.value)}
                          placeholder="What should the app have answered?"
                          rows={3}
                          required
                        />
                      </div>
                      <PromoteExpectedDocFields
                        idPrefix="conversation-promote"
                        documents={docPreview}
                        selectedIds={expectedDocIds}
                        onSelectedIdsChange={setExpectedDocIds}
                        extraDocIds={extraDocIds}
                        onExtraDocIdsChange={setExtraDocIds}
                      />
                    </div>
                    <DialogFooter>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => setPromoteOpen(false)}
                      >
                        Cancel
                      </Button>
                      <Button type="submit" disabled={promoteMutation.isPending}>
                        {promoteMutation.isPending ? "Adding…" : "Add to test set"}
                      </Button>
                    </DialogFooter>
                  </form>
                </DialogContent>
              </Dialog>
            </>
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
