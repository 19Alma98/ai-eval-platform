"use client";

import { MetricsSetList } from "@/features/metrics/metrics-set-list";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";

export default function MetricsPage() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return <MetricsSetList projectId={projectId} />;
}
