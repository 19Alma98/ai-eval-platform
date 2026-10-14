"use client";

import { Suspense } from "react";
import { LoadingBlock } from "@/components/loading-block";
import { PageIntro } from "@/components/page-intro";
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
      <PageIntro
        title="Traces"
        glossary="Every call your app made, step by step: what was retrieved, what the model saw and what it answered."
      />
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
