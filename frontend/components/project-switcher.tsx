"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronsUpDown, FolderPlus, Settings2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { CreateProjectDialog } from "@/features/projects/create-project-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { projectFallback } from "@/lib/project-fallback";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { projectsQueryOptions } from "@/lib/queries/projects";

export function ProjectSwitcher() {
  const router = useRouter();
  const { projectId, setProjectId, clearProjectId } = useProjectId();
  const { data: projects, isLoading, refetch } = useQuery(projectsQueryOptions());
  const [createOpen, setCreateOpen] = useState(false);

  const current = projects?.find((p) => p.id === projectId);

  // Saved/linked project no longer exists (deleted elsewhere): move to a valid one
  // instead of showing "Unknown project" with every request failing. Refetch first so
  // a project created after the list was cached isn't mistaken for a deleted one.
  const handledStaleId = useRef<string | null>(null);
  useEffect(() => {
    if (projectFallback(projectId, projects).action === "keep") return;
    if (handledStaleId.current === projectId) return;
    handledStaleId.current = projectId;
    void refetch().then(({ data }) => {
      const fallback = projectFallback(projectId, data);
      if (fallback.action === "switch") {
        toast.info(`That project no longer exists. Switched to ${fallback.to.name}.`);
        setProjectId(fallback.to.id);
      } else if (fallback.action === "clear") {
        clearProjectId();
      }
    });
  }, [projectId, projects, refetch, setProjectId, clearProjectId]);

  function goToManageProjects() {
    router.push(withProjectQuery("/projects", projectId));
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="outline"
              size="sm"
              className="h-8 max-w-[300px] justify-between gap-2 font-normal"
            />
          }
        >
          <span className="text-xs text-muted-foreground">Project</span>
          <span className="truncate font-medium">
            {isLoading
              ? "Loading…"
              : current?.name ?? (projectId ? "Unknown project" : "Select project")}
          </span>
          <ChevronsUpDown className="size-3.5 shrink-0 opacity-50" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-[260px]">
          {projects?.length ? (
            projects.map((p) => (
              <DropdownMenuItem
                key={p.id}
                onClick={() => setProjectId(p.id)}
                className={p.id === projectId ? "bg-row-selected" : undefined}
              >
                <span className="text-xs text-muted-foreground">Project</span>
          <span className="truncate font-medium">{p.name}</span>
              </DropdownMenuItem>
            ))
          ) : (
            <DropdownMenuItem disabled>No projects</DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={() => {
              setCreateOpen(true);
            }}
          >
            <FolderPlus className="size-4" />
            New project…
          </DropdownMenuItem>
          <DropdownMenuItem onClick={goToManageProjects}>
            <Settings2 className="size-4" />
            Manage projects
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <CreateProjectDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        showTrigger={false}
      />
    </>
  );
}
