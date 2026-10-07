"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState, type SubmitEvent } from "react";
import { toast } from "sonner";
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
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import { createAppConfig } from "@/lib/api/app-configs";
import { appConfigsQueryKey } from "./use-app-configs";

const EMPTY_JSON = "{}";

function parseJsonObject(raw: string, field: string): Record<string, unknown> {
  const trimmed = raw.trim() || EMPTY_JSON;
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new Error(`${field} must be valid JSON`);
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${field} must be a JSON object`);
  }
  return parsed as Record<string, unknown>;
}

export function CreateAppConfigDialog({
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
  const [description, setDescription] = useState("");
  const [promptJson, setPromptJson] = useState(EMPTY_JSON);
  const [modelJson, setModelJson] = useState(EMPTY_JSON);
  const [retrievalJson, setRetrievalJson] = useState(EMPTY_JSON);

  const create = useMutation({
    mutationFn: () => {
      const prompt = parseJsonObject(promptJson, "Prompt");
      const model = parseJsonObject(modelJson, "Model");
      const retrieval = parseJsonObject(retrievalJson, "Retrieval");
      return createAppConfig(projectId, {
        name: name.trim(),
        description: description.trim() || undefined,
        prompt,
        model,
        retrieval,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: appConfigsQueryKey(projectId),
      });
      toast.success("App config version created");
      setName("");
      setDescription("");
      setPromptJson(EMPTY_JSON);
      setModelJson(EMPTY_JSON);
      setRetrievalJson(EMPTY_JSON);
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

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    create.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger
        render={
          <Button type="button" size="sm">
            <Plus className="size-4" />
            New version
          </Button>
        }
      />
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Create app config</DialogTitle>
            <DialogDescription>
              Register a new immutable version for a config family. Each save
              bumps the version number for that name.
            </DialogDescription>
          </DialogHeader>
          <div className="flex max-h-[min(60vh,480px)] flex-col gap-3 overflow-y-auto py-4">
            <div className="flex flex-col gap-2">
              <label htmlFor="app-config-name" className="text-sm font-medium">
                Family name
              </label>
              <Input
                id="app-config-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="rag-assistant"
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <label
                htmlFor="app-config-description"
                className="text-sm font-medium"
              >
                Description
              </label>
              <Input
                id="app-config-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional notes"
              />
            </div>
            <JsonField
              id="app-config-prompt"
              label="Prompt (JSON object)"
              value={promptJson}
              onChange={setPromptJson}
            />
            <JsonField
              id="app-config-model"
              label="Model (JSON object)"
              value={modelJson}
              onChange={setModelJson}
            />
            <JsonField
              id="app-config-retrieval"
              label="Retrieval (JSON object)"
              value={retrievalJson}
              onChange={setRetrievalJson}
            />
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

function JsonField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <Textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="min-h-[88px] font-mono text-xs"
        spellCheck={false}
      />
    </div>
  );
}
