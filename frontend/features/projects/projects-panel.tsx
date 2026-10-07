"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { PageIntro } from "@/components/page-intro";
import { RelativeTime } from "@/components/relative-time";
import { Button } from "@/components/ui/button";
import { formatErrorForUi } from "@/lib/api/client";
import { deleteProject } from "@/lib/api/projects";
import type { Project } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { useProjectId } from "@/lib/project-store";
import {
  projectsQueryKey,
  projectsQueryOptions,
} from "@/lib/queries/projects";
import { CreateProjectDialog } from "./create-project-dialog";

export const PROJECTS_PANEL_ID = "projects-panel";

export function ProjectsPanel({
  compact = false,
}: {
  /** When true, omit the page intro (used as a section above the dashboard). */
  compact?: boolean;
}) {
  const { projectId, setProjectId, clearProjectId } = useProjectId();
  const queryClient = useQueryClient();
  const query = useQuery(projectsQueryOptions());
  const [createOpen, setCreateOpen] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const remove = useMutation({
    mutationFn: (id: string) => deleteProject(id),
    onSuccess: async (_data, id) => {
      await queryClient.invalidateQueries({ queryKey: projectsQueryKey });
      toast.success("Project deleted");
      if (id === projectId) {
        clearProjectId();
      }
      setDeletingId(null);
    },
    onError: (err) => {
      const message = formatErrorForUi(err);
      toast.error(message);
      setDeletingId(null);
    },
  });

  function handleDelete(project: Project) {
    const ok = window.confirm(
      `Delete project “${project.name}”? This removes all related data and cannot be undone.`,
    );
    if (!ok) return;
    setDeletingId(project.id);
    remove.mutate(project.id);
  }

  if (query.isLoading) {
    return <LoadingBlock className="min-h-[160px]" />;
  }

  if (query.isError) {
    const err = query.error;
    const message = formatErrorForUi(err);
    return (
      <ErrorState
        title="Could not load projects"
        message={message}
        onRetry={() => query.refetch()}
      />
    );
  }

  const projects = query.data ?? [];

  return (
    <section
      id={PROJECTS_PANEL_ID}
      className={cn("scroll-mt-4", compact && "mb-6")}
    >
      {!compact ? (
        <PageIntro
          title="Projects"
          glossary="Create and select a project to scope traces, datasets, metrics, and evaluation runs."
        />
      ) : (
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold tracking-tight text-foreground">
            Projects
          </h2>
          {projects.length > 0 ? (
            <CreateProjectDialog open={createOpen} onOpenChange={setCreateOpen} />
          ) : null}
        </div>
      )}

      {!compact && projects.length > 0 ? (
        <div className="mb-3 flex justify-end">
          <CreateProjectDialog open={createOpen} onOpenChange={setCreateOpen} />
        </div>
      ) : null}

      {projects.length === 0 ? (
        <EmptyState
          title="No projects yet"
          description="Create a project to get started with traces and evaluations."
          action={
            <CreateProjectDialog open={createOpen} onOpenChange={setCreateOpen} />
          }
        />
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border bg-surface">
          {projects.map((p) => {
            const selected = p.id === projectId;
            return (
              <li
                key={p.id}
                className={cn(
                  "flex items-center gap-2 px-3 py-2",
                  selected && "bg-row-selected",
                )}
              >
                <button
                  type="button"
                  onClick={() => setProjectId(p.id)}
                  className="min-w-0 flex-1 rounded-md px-1 py-1 text-left transition-colors hover:bg-row-hover"
                >
                  <span className="block truncate text-sm font-medium text-foreground">
                    {p.name}
                  </span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-xs text-muted-foreground">
                    <span>{p.slug}</span>
                    <RelativeTime date={p.created_at} />
                  </span>
                </button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="shrink-0 text-muted-foreground hover:text-status-fail"
                  disabled={remove.isPending && deletingId === p.id}
                  aria-label={`Delete ${p.name}`}
                  onClick={() => handleDelete(p)}
                >
                  <Trash2 className="size-4" />
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
