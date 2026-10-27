"use client";

import { Suspense } from "react";
import { LoadingBlock } from "@/components/loading-block";
import { ProductionHeader } from "@/components/production-header";
import { ProjectRequired } from "@/components/project-required";
import { TraceList } from "@/features/traces/trace-list";
import { useProjectId } from "@/lib/project-store";

function TracesPageContent() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return (
    <>
      <ProductionHeader active="traces" />
      <TraceList projectId={projectId} />
    </>
  );
}

export default function TracesPage() {
  return (
    <Suspense fallback={<LoadingBlock className="min-h-[240px]" />}>
      <TracesPageContent />
    </Suspense>
  );
}
