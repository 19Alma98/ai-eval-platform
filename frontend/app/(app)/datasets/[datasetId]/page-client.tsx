"use client";

import { useParams } from "next/navigation";
import { DatasetDetailView } from "@/features/datasets/dataset-detail";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";

export default function DatasetDetailPage() {
  const params = useParams();
  const datasetId =
    typeof params.datasetId === "string" ? params.datasetId : "";
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  if (!datasetId) {
    return null;
  }

  return <DatasetDetailView projectId={projectId} datasetId={datasetId} />;
}
