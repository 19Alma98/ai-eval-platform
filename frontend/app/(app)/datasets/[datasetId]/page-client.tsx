"use client";

import { useParams, usePathname } from "next/navigation";
import { DatasetDetailView } from "@/features/datasets/dataset-detail";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";
import { resolveStaticExportParam } from "@/lib/static-export-params";

export default function DatasetDetailPage() {
  const params = useParams();
  const pathname = usePathname();
  const datasetId = resolveStaticExportParam(
    params.datasetId,
    pathname,
    /^\/datasets\/([^/]+)/,
  );
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  if (!datasetId) {
    return null;
  }

  return <DatasetDetailView projectId={projectId} datasetId={datasetId} />;
}
