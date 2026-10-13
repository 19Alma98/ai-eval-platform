"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState, type SubmitEvent } from "react";
import { Plus, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import { toast } from "sonner";
import { useDatasets } from "@/features/datasets/use-datasets";
import { ErrorState } from "@/components/error-state";
import { JudgeClaimsTable } from "@/components/judge-claims-table";
import { LoadingBlock } from "@/components/loading-block";
import { MetaItem, PageHeader } from "@/components/page-header";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
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
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, formatErrorForUi } from "@/lib/api/client";
import {
  promoteLiveInteraction,
  rescoreLiveInteraction,
  reviewLiveScore,
} from "@/lib/api/live-runs";
import type { LiveInteractionScore, TraceScore } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatScore } from "@/lib/format";
import { metricInfo } from "@/lib/metrics-catalog";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { LIVE_VERDICT_LABELS, liveVerdict } from "./live-verdict";
import { FEEDBACK_NAME, feedbackThumb } from "./trace-feedback";
import { liveRunQueryKey, useLiveRun } from "./use-live-runs";

function ScoreReviewControls({
  score,
  interactionId,
  projectId,
}: {
  score: LiveInteractionScore;
  interactionId: string;
  projectId: string | null;
}) {
  const queryClient = useQueryClient();
  const judgeExplanation = score.explanation ?? "";
  const existing = score.review;
  const [disagreeOpen, setDisagreeOpen] = useState(false);
  const [explanation, setExplanation] = useState(
    existing?.corrected_explanation ?? judgeExplanation,
  );
  const [note, setNote] = useState(existing?.note ?? "");

  const mutation = useMutation({
    mutationFn: (verdict: "agree" | "disagree") => {
      const trimmed = explanation.trim();
      const changed =
        verdict === "disagree" && trimmed.length > 0 && trimmed !== judgeExplanation.trim();
      return reviewLiveScore(score.id, {
        verdict,
        corrected_explanation: changed ? trimmed : undefined,
        note: note.trim() || undefined,
      });
    },
    onSuccess: async () => {
      toast.success("Review saved");
      setDisagreeOpen(false);
      await queryClient.invalidateQueries({
        queryKey: liveRunQueryKey(interactionId, projectId ?? ""),
      });
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  return (
    <div className="mt-3 flex flex-col gap-2 border-t border-border pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">
          {existing
            ? existing.verdict === "agree"
              ? "You confirmed this verdict."
              : "You marked this verdict as wrong."
            : "Is the judge right?"}
        </span>
        <div className="flex-1" />
        <Button
          type="button"
          size="sm"
          variant={existing?.verdict === "agree" ? "default" : "outline"}
          className="h-7"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate("agree")}
        >
          <ThumbsUp className="size-3.5" />
          Correct
        </Button>
        <Button
          type="button"
          size="sm"
          variant={existing?.verdict === "disagree" ? "default" : "outline"}
          className="h-7"
          disabled={mutation.isPending}
          onClick={() => setDisagreeOpen((o) => !o)}
          aria-expanded={disagreeOpen}
        >
          <ThumbsDown className="size-3.5" />
          Wrong
        </Button>
      </div>
      {disagreeOpen ? (
        <div className="flex flex-col gap-2 rounded-md bg-surface-2 p-3">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            What should the judge have said?
            <Textarea
              value={explanation}
              onChange={(e) => setExplanation(e.target.value)}
              rows={3}
              className="bg-background text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Note (optional)
            <Textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              className="bg-background text-sm"
            />
          </label>
          <Button
            type="button"
            size="sm"
            className="self-end"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate("disagree")}
          >
            {mutation.isPending ? "Saving…" : "Save review"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

const SOURCE_LABELS: Record<string, string> = {
  sdk: "SDK metric",
  human: "User feedback",
  judge: "External judge",
};

function TraceScoreCard({ score }: { score: TraceScore }) {
  const isFeedback = score.name === FEEDBACK_NAME;
  const thumb = isFeedback ? feedbackThumb([score]) : null;
  return (
    <div className="rounded-lg border border-border bg-surface p-4 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 font-medium text-foreground">
          {thumb === "up" ? (
            <ThumbsUp className="size-4" aria-hidden />
          ) : thumb === "down" ? (
            <ThumbsDown className="size-4" aria-hidden />
          ) : null}
          {isFeedback ? "User feedback" : score.name}
          <Badge variant="outline" className="font-normal">
            {SOURCE_LABELS[score.source] ?? score.source}
          </Badge>
        </span>
        <span className="flex items-center gap-2">
          {isFeedback ? null : (
            <span className="tabular-nums text-muted-foreground">
              {formatScore(score.value)}
              {score.threshold != null ? ` / needs ${formatScore(score.threshold)}` : ""}
            </span>
          )}
          {score.label ? <StatusBadge status={score.label} /> : null}
        </span>
      </div>
      {score.author ? (
        <p className="mt-0.5 text-xs text-muted-foreground">by {score.author}</p>
      ) : null}
      {score.explanation ? <p className="mt-2 text-foreground">{score.explanation}</p> : null}
    </div>
  );
}

export function LiveRunDetail({ interactionId }: { interactionId: string }) {
  const { projectId } = useProjectId();
  const queryClient = useQueryClient();
  const router = useRouter();
  const query = useLiveRun(interactionId, projectId);
  const datasets = useDatasets(projectId);
  const [promoteOpen, setPromoteOpen] = useState(false);
  const [datasetId, setDatasetId] = useState("");
  const [expectedOutput, setExpectedOutput] = useState("");
  const [expectedDocIds, setExpectedDocIds] = useState<string[]>([]);
  const [extraDocIds, setExtraDocIds] = useState("");

  const row = query.data;

  const rescoreMutation = useMutation({
    mutationFn: () => rescoreLiveInteraction(interactionId),
    onSuccess: async () => {
      toast.success("Judge re-run");
      await queryClient.invalidateQueries({
        queryKey: liveRunQueryKey(interactionId, projectId ?? ""),
      });
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  const promoteMutation = useMutation({
    mutationFn: () =>
      promoteLiveInteraction(interactionId, {
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
        router.push(
          withProjectQuery(`/datasets/${item.dataset_id}`, projectId),
        );
      }
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  const docPreview = useMemo(() => {
    if (!row) return [];
    return row.documents.map((d) => ({
      id: String(d.id ?? ""),
      title: typeof d.title === "string" ? d.title : undefined,
      text: typeof d.text === "string" ? d.text : undefined,
    }));
  }, [row]);

  const goldDocIds = Array.from(
    new Set([
      ...expectedDocIds,
      ...extraDocIds
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
    ]),
  );

  const reviewedKinds = (row?.scores ?? []).filter((s) => s.review).length;

  if (query.isLoading) return <LoadingBlock />;
  if (query.isError || !row) {
    const wrongProject =
      query.error instanceof ApiError &&
      query.error.message === "Live interaction not found in this project.";
    return (
      <ErrorState
        message={
          wrongProject
            ? "This answer belongs to another project."
            : "Could not load this answer."
        }
      />
    );
  }

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
    promoteMutation.mutate();
  }

  const verdict = liveVerdict(row);
  const title =
    row.question.length > 90 ? `${row.question.slice(0, 90).trimEnd()}…` : row.question;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        breadcrumbs={[
          { label: "Live traffic", href: withProjectQuery("/live-runs", projectId) },
          { label: "Answer" },
        ]}
        title={title}
        badges={
          <span
            className={cn(
              "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium",
              verdict === "failing"
                ? "bg-status-fail-bg text-status-fail"
                : verdict === "passing"
                  ? "bg-status-ok-bg text-status-ok"
                  : "bg-status-unset-bg text-status-unset",
            )}
          >
            {LIVE_VERDICT_LABELS[verdict]}
          </span>
        }
        meta={
          <>
            <MetaItem label="Received">
              <RelativeTime date={row.created_at} />
            </MetaItem>
            {row.scores.length > 0 ? (
              <MetaItem label="Reviewed">
                {reviewedKinds} of {row.scores.length} verdicts
              </MetaItem>
            ) : null}
          </>
        }
        actions={
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={rescoreMutation.isPending}
              onClick={() => rescoreMutation.mutate()}
              title="Ask the judge to score this answer again"
            >
              <RotateCcw className="size-4" />
              {rescoreMutation.isPending ? "Re-scoring…" : "Re-run judge"}
            </Button>
            <Dialog open={promoteOpen} onOpenChange={setPromoteOpen}>
              <DialogTrigger
                render={
                  <Button
                    type="button"
                    size="sm"
                    variant={verdict === "failing" ? "default" : "outline"}
                  >
                    <Plus className="size-4" />
                    Add to test set
                  </Button>
                }
              />
              <DialogContent className="sm:max-w-lg">
                <form onSubmit={onPromote}>
                  <DialogHeader>
                    <DialogTitle>Add this question to a test set</DialogTitle>
                    <DialogDescription>
                      Future experiments will be checked on it. Write the correct
                      answer yourself — the production answer is what is being
                      tested, so it is never copied.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="flex flex-col gap-4 py-4">
                    <div className="flex flex-col gap-1.5">
                      <label htmlFor="promote-dataset" className="text-sm font-medium">
                        Test set
                      </label>
                      <Select value={datasetId} onValueChange={(v) => setDatasetId(v ?? "")}>
                        <SelectTrigger id="promote-dataset" className="w-full">
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
                      <label htmlFor="promote-expected" className="text-sm font-medium">
                        Correct answer
                      </label>
                      <Textarea
                        id="promote-expected"
                        value={expectedOutput}
                        onChange={(e) => setExpectedOutput(e.target.value)}
                        placeholder="What should the app have answered?"
                        rows={3}
                        required
                      />
                    </div>
                    {docPreview.length > 0 ? (
                      <fieldset className="flex flex-col gap-1.5 text-sm">
                        <legend className="mb-1.5 font-medium">
                          Which documents contain the answer?
                        </legend>
                        {docPreview.map((d) => (
                          <label key={d.id} className="flex items-center gap-2">
                            <input
                              type="checkbox"
                              className="size-4 accent-primary"
                              checked={expectedDocIds.includes(d.id)}
                              onChange={(e) =>
                                setExpectedDocIds((prev) =>
                                  e.target.checked
                                    ? [...prev, d.id]
                                    : prev.filter((x) => x !== d.id),
                                )
                              }
                            />
                            <span className="text-foreground">{d.title ?? d.id}</span>
                            {d.title ? (
                              <Badge variant="outline" className="font-normal">
                                {d.id}
                              </Badge>
                            ) : null}
                          </label>
                        ))}
                      </fieldset>
                    ) : null}
                    <div className="flex flex-col gap-1.5">
                      <label htmlFor="promote-extra" className="text-sm font-medium">
                        Other documents that should have been found{" "}
                        <span className="font-normal text-muted-foreground">(optional)</span>
                      </label>
                      <Input
                        id="promote-extra"
                        value={extraDocIds}
                        onChange={(e) => setExtraDocIds(e.target.value)}
                        placeholder="Document IDs, comma-separated"
                      />
                    </div>
                  </div>
                  <DialogFooter>
                    <Button type="button" variant="outline" onClick={() => setPromoteOpen(false)}>
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
        }
        className="mb-0"
      />

      {row.score_warning ? (
        <p className="rounded-md border border-status-warn bg-status-warn-bg px-3 py-2 text-sm text-status-warn">
          {row.score_warning}
        </p>
      ) : null}
      {row.error_message ? (
        <p className="rounded-md border border-status-fail bg-status-fail-bg px-3 py-2 text-sm text-status-fail">
          {row.error_message}
        </p>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          {title !== row.question ? (
            <section className="flex flex-col gap-1.5">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Question
              </h2>
              <p className="rounded-md border border-border bg-surface px-3 py-2 text-sm whitespace-pre-wrap">
                {row.question}
              </p>
            </section>
          ) : null}
          <section className="flex flex-col gap-1.5">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              App answer
            </h2>
            <p className="rounded-md border border-border bg-surface px-3 py-2 text-sm whitespace-pre-wrap">
              {row.answer}
            </p>
          </section>
          <section className="flex flex-col gap-1.5">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Retrieved documents
            </h2>
            {docPreview.length === 0 ? (
              <p className="text-sm text-status-warn">
                No documents were retrieved for this answer.
              </p>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {docPreview.map((doc) => (
                  <li
                    key={doc.id}
                    className="rounded-md border border-border bg-surface px-3 py-2 text-sm"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-foreground">{doc.title ?? doc.id}</span>
                      {doc.title ? (
                        <Badge variant="outline" className="font-normal">
                          {doc.id}
                        </Badge>
                      ) : null}
                    </div>
                    {doc.text ? (
                      <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-muted-foreground">
                        {doc.text}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <section className="flex flex-col gap-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Judge verdicts
          </h2>
          {row.scores.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              The judge has not scored this answer yet.
            </p>
          ) : (
            row.scores.map((score) => {
              const info = metricInfo(score.kind);
              return (
                <div
                  key={score.id}
                  className="rounded-lg border border-border bg-surface p-4 text-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-foreground" title={info.description}>
                      {info.label}
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="tabular-nums text-muted-foreground">
                        {formatScore(score.score)}
                        {score.threshold != null ? ` / needs ${formatScore(score.threshold)}` : ""}
                      </span>
                      {score.label ? <StatusBadge status={score.label} /> : null}
                    </span>
                  </div>
                  {info.description ? (
                    <p className="mt-0.5 text-xs text-muted-foreground">{info.description}</p>
                  ) : null}
                  {score.explanation ? (
                    <p className="mt-2 text-foreground">{score.explanation}</p>
                  ) : null}
                  {score.review?.corrected_explanation ? (
                    <p className="mt-2 rounded-md bg-surface-2 px-2 py-1.5 text-foreground">
                      <span className="text-xs font-medium text-muted-foreground">
                        Reviewer correction:{" "}
                      </span>
                      {score.review.corrected_explanation}
                    </p>
                  ) : null}
                  <div className="mt-2">
                    <JudgeClaimsTable metadata={score.metadata} title="Claims checked" />
                  </div>
                  <ScoreReviewControls
                    key={[
                      score.id,
                      score.explanation ?? "",
                      score.review?.corrected_explanation ?? "",
                      score.review?.note ?? "",
                    ].join("|")}
                    score={score}
                    interactionId={interactionId}
                    projectId={projectId}
                  />
                </div>
              );
            })
          )}
        </section>

        {(row.trace_scores ?? []).length > 0 ? (
          <section className="flex flex-col gap-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              SDK scores &amp; feedback
            </h2>
            {(row.trace_scores ?? []).map((score) => (
              <TraceScoreCard key={score.id} score={score} />
            ))}
          </section>
        ) : null}
      </div>
    </div>
  );
}
