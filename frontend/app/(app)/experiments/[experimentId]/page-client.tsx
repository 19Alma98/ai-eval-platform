"use client";

import { useParams, usePathname } from "next/navigation";
import { ExperimentDetailView } from "@/features/experiments/experiment-detail";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";
import { resolveStaticExportParam } from "@/lib/static-export-params";

export default function ExperimentDetailPage() {
  const params = useParams();
  const pathname = usePathname();
  const experimentId = resolveStaticExportParam(
    params.experimentId,
    pathname,
    /^\/experiments\/([^/]+)/,
  );
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
