"use client";

import { DatasetList } from "@/features/datasets/dataset-list";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";

export default function DatasetsPage() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return <DatasetList />;
}
