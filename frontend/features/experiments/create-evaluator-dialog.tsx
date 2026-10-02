"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
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
import { ApiError } from "@/lib/api/client";
import { createEvaluator } from "@/lib/api/evaluators";
import { evaluatorsQueryKey } from "./use-experiments";

const EVALUATOR_PRESETS = [
  {
    label: "Exact match",
    type: "deterministic",
    config: { kind: "exact_match" },
  },
  {
    label: "Contains",
    type: "deterministic",
    config: { kind: "contains" },
  },
  {
    label: "Correctness (LLM)",
    type: "llm_judge",
    config: { kind: "correctness" },
  },
  {
    label: "Groundedness (LLM)",
    type: "llm_judge",
    config: { kind: "groundedness" },
  },
  {
    label: "Answer relevance (LLM)",
    type: "llm_judge",
    config: { kind: "answer_relevance" },
  },
] as const;

export function CreateEvaluatorDialog({
  projectId,
  open,
  onOpenChange,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [presetIndex, setPresetIndex] = useState("0");

  const preset = EVALUATOR_PRESETS[Number(presetIndex)] ?? EVALUATOR_PRESETS[0];

  const create = useMutation({
    mutationFn: () =>
      createEvaluator(projectId, {
        name: name.trim(),
        type: preset.type,
        config: { ...preset.config },
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: evaluatorsQueryKey(projectId),
      });
      toast.success("Evaluator created");
      setName("");
      setPresetIndex("0");
      onOpenChange(false);
    },
    onError: (err) => {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Create failed";
      toast.error(message);
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    create.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Create evaluator</DialogTitle>
            <DialogDescription>
              Add a scoring rule to run against experiment outputs.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-4">
            <div className="flex flex-col gap-2">
              <label htmlFor="evaluator-create-name" className="text-sm font-medium">
                Name
              </label>
              <Input
                id="evaluator-create-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Exact match — prod"
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="evaluator-create-preset" className="text-sm font-medium">
                Preset
              </label>
              <Select value={presetIndex} onValueChange={(v) => setPresetIndex(v ?? "0")}>
                <SelectTrigger id="evaluator-create-preset">
                  <SelectValue placeholder="Select preset" />
                </SelectTrigger>
                <SelectContent>
                  {EVALUATOR_PRESETS.map((p, i) => (
                    <SelectItem key={p.label} value={String(i)}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || create.isPending}>
              {create.isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
