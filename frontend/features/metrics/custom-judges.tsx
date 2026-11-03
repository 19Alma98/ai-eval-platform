"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";
import { Gavel, Plus } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
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
import { Textarea } from "@/components/ui/textarea";
import { formatErrorForUi } from "@/lib/api/client";
import {
  createEvaluator,
  previewEvaluator,
  type EvaluatorPreview,
} from "@/lib/api/evaluators";
import type { Evaluator } from "@/lib/api/types";
import { evaluatorsQueryKey, useEvaluators } from "@/features/experiments/use-experiments";
import {
  EMPTY_JUDGE_DRAFT,
  JUDGE_FIELD_LABELS,
  buildJudgeConfig,
  judgeDraftError,
  latestCustomJudges,
  nextJudgeVersion,
  type JudgeDraft,
  type JudgeField,
  type JudgeScale,
} from "./custom-judge";

/** Project LLM judges described in plain language (`kind: custom_judge`). */
export function CustomJudges({ projectId }: { projectId: string }) {
  const query = useEvaluators(projectId);
  const [open, setOpen] = useState(false);
  const all = query.data ?? [];
  const judges = latestCustomJudges(all);

  return (
    <section
      aria-labelledby="custom-judges-title"
      className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="custom-judges-title" className="text-sm font-semibold text-foreground">
          Custom judges
        </h2>
        <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)}>
          <Plus className="size-4" />
          New judge
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        An LLM grades each answer against criteria you write (tone, format, policy…). Add a
        judge to a metrics set to score experiments with it; mark it <em>live</em> to also
        score production answers. From code: <code>opengrade.LlmJudge(...)</code>.
      </p>
      {judges.length > 0 ? (
        <ul className="flex flex-col gap-2" aria-label="Custom judges">
          {judges.map((judge) => (
            <JudgeRow key={judge.id} judge={judge} />
          ))}
        </ul>
      ) : null}
      <CreateJudgeDialog
        projectId={projectId}
        evaluators={all}
        open={open}
        onOpenChange={setOpen}
      />
    </section>
  );
}

function JudgeRow({ judge }: { judge: Evaluator }) {
  const config = judge.config ?? {};
  const criteria = typeof config.criteria === "string" ? config.criteria : "";
  const fields = Array.isArray(config.fields) ? (config.fields as string[]) : ["input", "output"];
  return (
    <li className="flex flex-col gap-1 rounded border border-border bg-surface-2 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <Gavel className="size-3.5 text-muted-foreground" aria-hidden />
        <span className="font-mono text-xs font-medium text-foreground">{judge.name}</span>
        <span className="text-xs text-muted-foreground">v{judge.version}</span>
        <Badge variant="secondary">{config.scale === "binary" ? "pass / fail" : "1–5"}</Badge>
        {config.live === true ? <Badge>live</Badge> : null}
        <span className="text-xs text-muted-foreground">reads: {fields.join(", ")}</span>
      </div>
      <p className="line-clamp-2 text-sm text-muted-foreground">{criteria}</p>
    </li>
  );
}

const FIELD_OPTIONS = Object.keys(JUDGE_FIELD_LABELS) as JudgeField[];

function CreateJudgeDialog({
  projectId,
  evaluators,
  open,
  onOpenChange,
}: {
  projectId: string;
  evaluators: Evaluator[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [draft, setDraft] = useState<JudgeDraft>(EMPTY_JUDGE_DRAFT);
  const [sampleInput, setSampleInput] = useState("");
  const [sampleOutput, setSampleOutput] = useState("");
  const [preview, setPreview] = useState<EvaluatorPreview | null>(null);

  const problem = judgeDraftError(name, draft);

  function update(patch: Partial<JudgeDraft>) {
    setDraft((d) => ({ ...d, ...patch }));
    setPreview(null);
  }

  function toggleField(field: JudgeField, checked: boolean) {
    update({
      fields: checked ? [...draft.fields, field] : draft.fields.filter((f) => f !== field),
    });
  }

  function reset() {
    setName("");
    setDraft(EMPTY_JUDGE_DRAFT);
    setSampleInput("");
    setSampleOutput("");
    setPreview(null);
  }

  const create = useMutation({
    mutationFn: () =>
      createEvaluator(projectId, {
        name: name.trim(),
        type: "llm_judge",
        config: buildJudgeConfig(draft),
        version: nextJudgeVersion(evaluators, name),
      }),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: evaluatorsQueryKey(projectId) });
      toast.success(`Judge ${created.name} v${created.version} created`);
      reset();
      onOpenChange(false);
    },
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  const tryIt = useMutation({
    mutationFn: () =>
      previewEvaluator(projectId, {
        config: buildJudgeConfig(draft),
        sample: { input: sampleInput || null, output: sampleOutput },
      }),
    onSuccess: setPreview,
    onError: (err) => toast.error(formatErrorForUi(err)),
  });

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (problem) return;
    create.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>New custom judge</DialogTitle>
            <DialogDescription>
              Describe what a good answer looks like. Saving a judge with an existing name
              creates a new version.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-4">
            <div className="flex flex-col gap-2">
              <label htmlFor="judge-name" className="text-sm font-medium">
                Name
              </label>
              <Input
                id="judge-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. tone"
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="judge-criteria" className="text-sm font-medium">
                Criteria
              </label>
              <Textarea
                id="judge-criteria"
                value={draft.criteria}
                onChange={(e) => update({ criteria: e.target.value })}
                placeholder="The answer is polite and professional, uses no slang and never blames the user."
                rows={4}
              />
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="judge-scale" className="text-sm font-medium">
                Scale
              </label>
              <Select
                value={draft.scale}
                onValueChange={(v) => update({ scale: (v ?? "1-5") as JudgeScale })}
              >
                <SelectTrigger id="judge-scale">
                  <SelectValue placeholder="Scale" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="1-5">1–5 rating (score 0–1)</SelectItem>
                  <SelectItem value="binary">Pass / fail (score 1 or 0)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <fieldset className="flex flex-col gap-1.5">
              <legend className="mb-1 text-sm font-medium">The judge also reads</legend>
              {FIELD_OPTIONS.map((field) => (
                <label key={field} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4 accent-primary"
                    checked={draft.fields.includes(field)}
                    onChange={(e) => toggleField(field, e.target.checked)}
                  />
                  {JUDGE_FIELD_LABELS[field]}
                </label>
              ))}
              <span className="text-xs text-muted-foreground">
                The answer is always included.
              </span>
            </fieldset>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4 accent-primary"
                checked={draft.live}
                onChange={(e) => update({ live: e.target.checked })}
              />
              Live: also score production answers
            </label>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <label htmlFor="judge-threshold" className="text-sm font-medium">
                  Pass mark (0–1)
                </label>
                <Input
                  id="judge-threshold"
                  inputMode="decimal"
                  value={draft.threshold}
                  onChange={(e) => update({ threshold: e.target.value })}
                  disabled={!draft.live}
                />
              </div>
              <div className="flex flex-col gap-2">
                <label htmlFor="judge-model" className="text-sm font-medium">
                  Judge model
                </label>
                <Input
                  id="judge-model"
                  value={draft.model}
                  onChange={(e) => update({ model: e.target.value })}
                  placeholder="Server default"
                />
              </div>
            </div>

            <div className="flex flex-col gap-2 rounded border border-border p-3">
              <span className="text-sm font-medium">Try it</span>
              {draft.fields.includes("input") ? (
                <Input
                  aria-label="Sample question"
                  value={sampleInput}
                  onChange={(e) => setSampleInput(e.target.value)}
                  placeholder="Sample question"
                />
              ) : null}
              <Textarea
                aria-label="Sample answer"
                value={sampleOutput}
                onChange={(e) => {
                  setSampleOutput(e.target.value);
                  setPreview(null);
                }}
                placeholder="Sample answer to grade"
                rows={2}
              />
              <div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={!draft.criteria.trim() || !sampleOutput.trim() || tryIt.isPending}
                  onClick={() => tryIt.mutate()}
                >
                  {tryIt.isPending ? "Grading…" : "Grade sample"}
                </Button>
              </div>
              {preview ? (
                <p className="text-sm" role="status">
                  <span className="font-medium tabular-nums">
                    {preview.label ?? (preview.score === null ? "—" : preview.score.toFixed(2))}
                  </span>{" "}
                  <span className="text-muted-foreground">{preview.explanation}</span>
                </p>
              ) : null}
            </div>
            {problem && name.trim() && draft.criteria.trim() ? (
              <p className="text-sm text-destructive">{problem}</p>
            ) : null}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={Boolean(problem) || create.isPending}>
              {create.isPending ? "Creating…" : "Create judge"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
