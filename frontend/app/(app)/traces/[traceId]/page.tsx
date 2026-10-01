"use client";

import { useParams } from "next/navigation";
import { ProjectRequired } from "@/features/traces/project-required";
import { TraceDetailView } from "@/features/traces/trace-detail-view";
import { useProjectId } from "@/lib/project-store";

export default function TraceDetailPage() {
  const params = useParams();
  const traceId = typeof params.traceId === "string" ? params.traceId : "";
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  if (!traceId) {
    return null;
  }

  return <TraceDetailView projectId={projectId} traceId={traceId} />;
}
