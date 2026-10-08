"use client";

import { useParams } from "next/navigation";
import { MetricsSetDetailView } from "@/features/metrics/metrics-set-detail";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";

export default function MetricsSetDetailPage() {
  const params = useParams();
  const metricsSetId =
    typeof params.metricsSetId === "string" ? params.metricsSetId : "";
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  if (!metricsSetId) {
    return null;
  }

  return (
    <MetricsSetDetailView projectId={projectId} metricsSetId={metricsSetId} />
  );
}
