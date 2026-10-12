"use client";

import { useParams, usePathname } from "next/navigation";
import { MetricsSetDetailView } from "@/features/metrics/metrics-set-detail";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";
import { resolveStaticExportParam } from "@/lib/static-export-params";

export default function MetricsSetDetailPage() {
  const params = useParams();
  const pathname = usePathname();
  const metricsSetId = resolveStaticExportParam(
    params.metricsSetId,
    pathname,
    /^\/metrics\/([^/]+)/,
  );
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
