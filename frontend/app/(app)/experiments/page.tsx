"use client";

import { ExperimentList } from "@/features/experiments/experiment-list";
import { ProjectRequired } from "@/features/traces/project-required";
import { useProjectId } from "@/lib/project-store";

export default function ExperimentsPage() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return <ExperimentList />;
}
