"use client";

import { Suspense } from "react";
import { LoadingBlock } from "@/components/loading-block";
import { PageIntro } from "@/components/page-intro";
import { LiveRunList } from "@/features/live-runs/live-run-list";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";

function LiveRunsPageContent() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return (
    <>
      <PageIntro
        title="Live traffic"
        glossary="Real questions from production, scored automatically by an LLM judge. Review the verdicts and turn failures into test cases."
      />
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
