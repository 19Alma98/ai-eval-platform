"use client";

import { Suspense } from "react";
import { LoadingBlock } from "@/components/loading-block";
import { ProjectRequired } from "@/components/project-required";
import { MonitoringDashboard } from "@/features/monitoring/monitoring-dashboard";
import { useProjectId } from "@/lib/project-store";

function MonitoringPageContent() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return <MonitoringDashboard projectId={projectId} />;
}

export default function MonitoringPage() {
  return (
    <Suspense fallback={<LoadingBlock className="min-h-[240px]" />}>
      <MonitoringPageContent />
    </Suspense>
  );
}
