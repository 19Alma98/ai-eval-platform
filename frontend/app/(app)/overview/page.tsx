"use client";

import { OverviewDashboard } from "@/features/overview/overview-dashboard";
import { ProjectsPanel } from "@/features/projects/projects-panel";
import { useProjectId } from "@/lib/project-store";

export default function OverviewPage() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return (
      <div className="mx-auto max-w-lg">
        <ProjectsPanel />
      </div>
    );
  }

  return (
    <div>
      <ProjectsPanel compact />
      <OverviewDashboard />
    </div>
  );
}
