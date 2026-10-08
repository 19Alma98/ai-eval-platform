"use client";

import { useParams } from "next/navigation";
import { ExperimentDetailView } from "@/features/experiments/experiment-detail";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";

export default function ExperimentDetailPage() {
  const params = useParams();
  const experimentId =
    typeof params.experimentId === "string" ? params.experimentId : "";
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  if (!experimentId) {
    return null;
  }

  return (
    <ExperimentDetailView projectId={projectId} experimentId={experimentId} />
  );
}
