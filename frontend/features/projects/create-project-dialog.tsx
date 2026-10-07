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
import { formatErrorForUi } from "@/lib/api/client";
import { createProject } from "@/lib/api/projects";
import { useProjectId } from "@/lib/project-store";
import { projectsQueryKey } from "@/lib/queries/projects";

export function CreateProjectDialog({
  open,
  onOpenChange,
  showTrigger = true,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  showTrigger?: boolean;
}) {
  const queryClient = useQueryClient();
  const { setProjectId } = useProjectId();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");

  const create = useMutation({
    mutationFn: () =>
      createProject({
        name: name.trim(),
        slug: slug.trim() || undefined,
      }),
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: projectsQueryKey });
      toast.success("Project created");
      setProjectId(project.id);
      setName("");
      setSlug("");
      onOpenChange(false);
    },
    onError: (err) => {
      const message = formatErrorForUi(err);
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
      {showTrigger ? (
        <DialogTrigger
          render={
            <Button type="button" size="sm">
              <Plus className="size-4" />
              New project
            </Button>
          }
        />
      ) : null}
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Create project</DialogTitle>
            <DialogDescription>
              A project scopes traces, datasets, metrics, and evaluation runs.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3 py-4">
            <div className="flex flex-col gap-2">
              <label htmlFor="project-create-name" className="text-sm font-medium">
                Name
              </label>
              <Input
                id="project-create-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My app"
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <label htmlFor="project-create-slug" className="text-sm font-medium">
                Slug
              </label>
              <Input
                id="project-create-slug"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder="Optional — derived from name if empty"
              />
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
