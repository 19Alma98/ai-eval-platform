"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronsUpDown, FolderPlus, Settings2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { CreateProjectDialog } from "@/features/projects/create-project-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { withProjectQuery } from "@/lib/project-href";
import { useProjectId } from "@/lib/project-store";
import { projectsQueryOptions } from "@/lib/queries/projects";

export function ProjectSwitcher() {
  const router = useRouter();
  const { projectId, setProjectId } = useProjectId();
  const { data: projects, isLoading } = useQuery(projectsQueryOptions());
  const [createOpen, setCreateOpen] = useState(false);

  const current = projects?.find((p) => p.id === projectId);

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
