"use client";

import { Suspense } from "react";
import { LoadingBlock } from "@/components/loading-block";
import { LiveRunList } from "@/features/live-runs/live-run-list";
import { ProductionHeader } from "@/components/production-header";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";

function LiveRunsPageContent() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return (
    <>
      <ProductionHeader active="answers" />
      <LiveRunList />
    </>
  );
}

export default function LiveRunsPage() {
  return (
    <Suspense fallback={<LoadingBlock className="min-h-[240px]" />}>
      <LiveRunsPageContent />
    </Suspense>
  );
}
