"use client";

import { OverviewDashboard } from "@/features/overview/overview-dashboard";
import { ProjectRequired } from "@/features/traces/project-required";
import { useProjectId } from "@/lib/project-store";

export default function OverviewPage() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return <OverviewDashboard />;
}
