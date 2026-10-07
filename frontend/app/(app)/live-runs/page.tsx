"use client";

import { PageIntro } from "@/components/page-intro";
import { LiveRunList } from "@/features/live-runs/live-run-list";
import { ProjectRequired } from "@/features/traces/project-required";
import { useProjectId } from "@/lib/project-store";

export default function LiveRunsPage() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return (
    <>
      <PageIntro
        title="Live runs"
        glossary="Prod-like interactions pushed via the SDK — gold-less LLM judge for groundedness / hallucination risk, plus light human review."
      />
      <LiveRunList />
    </>
  );
}
