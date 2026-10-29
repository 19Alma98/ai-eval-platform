"use client";

import { Suspense } from "react";
import { LoadingBlock } from "@/components/loading-block";
import { ProjectRequired } from "@/components/project-required";
import { AlertsPage } from "@/features/alerts/alerts-page";
import { useProjectId } from "@/lib/project-store";

function AlertsPageContent() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return <AlertsPage projectId={projectId} />;
}

export default function AlertsRoutePage() {
  return (
    <Suspense fallback={<LoadingBlock className="min-h-[240px]" />}>
      <AlertsPageContent />
    </Suspense>
  );
}
