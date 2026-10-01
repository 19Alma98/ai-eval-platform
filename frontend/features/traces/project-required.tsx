"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createProject } from "@/lib/api/projects";
import { useProjectId } from "@/lib/project-store";
import {
  projectsQueryKey,
  projectsQueryOptions,
} from "@/lib/queries/projects";
import { cn } from "@/lib/cn";

export function ProjectRequired() {
  const { setProjectId } = useProjectId();
  const queryClient = useQueryClient();
  const { data: projects, isLoading } = useQuery(projectsQueryOptions());
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
      setProjectId(project.id);
      setName("");
      setSlug("");
    },
  });

  function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    create.mutate();
  }

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <EmptyState
        title="Select a project"
        description="Choose an existing project or create one to view traces."
      />
      {isLoading ? null : projects?.length ? (
        <div className="rounded-md border border-border bg-surface p-4">
          <p className="mb-2 text-sm font-medium text-foreground">
            Existing projects
          </p>
          <ul className="flex flex-col gap-1">
            {projects.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => setProjectId(p.id)}
                  className={cn(
                    "w-full rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-row-hover",
                  )}
                >
                  <span className="font-medium">{p.name}</span>
                  <span className="ml-2 font-mono text-xs text-muted-foreground">
                    {p.slug}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <form
        onSubmit={handleCreate}
        className="space-y-3 rounded-md border border-border bg-surface p-4"
      >
        <p className="text-sm font-medium text-foreground">Create project</p>
        <div className="space-y-2">
          <Input
            placeholder="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <Input
            placeholder="Slug (optional)"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
        </div>
        {create.isError ? (
          <p className="text-sm text-status-fail">
            {create.error instanceof Error
              ? create.error.message
              : "Create failed"}
          </p>
        ) : null}
        <Button type="submit" size="sm" disabled={create.isPending}>
          {create.isPending ? "Creating…" : "Create project"}
        </Button>
      </form>
    </div>
  );
}
