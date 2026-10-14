"use client";

import { useParams, usePathname } from "next/navigation";
import { ProjectRequired } from "@/components/project-required";
import { TraceDetailView } from "@/features/traces/trace-detail";
import { useProjectId } from "@/lib/project-store";
import { resolveStaticExportParam } from "@/lib/static-export-params";

export default function TraceDetailPage() {
  const params = useParams();
  const pathname = usePathname();
  const traceId = resolveStaticExportParam(params.traceId, pathname, /^\/traces\/([^/]+)/);
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  if (!traceId) {
    return null;
  }

  return <TraceDetailView projectId={projectId} traceId={traceId} />;
}
