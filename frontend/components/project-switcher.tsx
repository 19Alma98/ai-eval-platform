"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronsUpDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { projectsQueryOptions } from "@/lib/queries/projects";
import { useProjectId } from "@/lib/project-store";

export function ProjectSwitcher() {
  const { projectId, setProjectId } = useProjectId();
  const { data: projects, isLoading } = useQuery(projectsQueryOptions());

  const current = projects?.find((p) => p.id === projectId);

  return (
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
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
