"use client";

import { Suspense } from "react";
import { LoadingBlock } from "@/components/loading-block";
import { ProjectRequired } from "@/components/project-required";
import { ExperimentsMatrixView } from "@/features/experiments/experiments-matrix-view";
import { useProjectId } from "@/lib/project-store";

function ExperimentsComparePageContent() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return <ExperimentsMatrixView projectId={projectId} />;
}

export default function ExperimentsComparePage() {
  return (
    <Suspense fallback={<LoadingBlock className="min-h-[240px]" />}>
      <ExperimentsComparePageContent />
    </Suspense>
  );
}
