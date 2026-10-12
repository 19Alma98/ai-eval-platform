"use client";

import { Suspense } from "react";
import { LoadingBlock } from "@/components/loading-block";
import { ExperimentList } from "@/features/experiments/experiment-list";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";

function ExperimentsPageContent() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return <ExperimentList />;
}

export default function ExperimentsPage() {
  return (
    <Suspense fallback={<LoadingBlock className="min-h-[240px]" />}>
      <ExperimentsPageContent />
    </Suspense>
  );
}
