"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronsUpDown, FolderPlus, Settings2 } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { CreateProjectDialog } from "@/features/projects/create-project-dialog";
import { PROJECTS_PANEL_ID } from "@/features/projects/projects-panel";
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
  const pathname = usePathname();
  const { projectId, setProjectId } = useProjectId();
  const { data: projects, isLoading } = useQuery(projectsQueryOptions());
  const [createOpen, setCreateOpen] = useState(false);

  const current = projects?.find((p) => p.id === projectId);

  function goToManageProjects() {
    if (pathname.startsWith("/overview")) {
      document
        .getElementById(PROJECTS_PANEL_ID)
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    router.push(withProjectQuery("/overview", projectId));
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="outline"
              size="sm"
              className="h-8 max-w-[220px] justify-between gap-2 font-normal"
            />
          }
        >
          <span className="truncate">
            {isLoading
              ? "Loading…"
              : current?.name ?? projectId ?? "Select project"}
          </span>
          <ChevronsUpDown className="size-3.5 shrink-0 opacity-50" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-[220px]">
          {projects?.length ? (
            projects.map((p) => (
              <DropdownMenuItem
                key={p.id}
                onClick={() => setProjectId(p.id)}
                className={p.id === projectId ? "bg-row-selected" : undefined}
              >
                <span className="truncate">{p.name}</span>
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
