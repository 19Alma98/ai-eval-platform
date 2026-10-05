"use client";

import { EmptyState } from "@/components/empty-state";
import { PageIntro } from "@/components/page-intro";
import { ProjectRequired } from "@/features/traces/project-required";
import { useProjectId } from "@/lib/project-store";

export default function MetricsPage() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return (
    <>
      <PageIntro
        title="Metriche"
        glossary="Evaluator packs and thresholds — what you measure on each test set run."
      />
      <EmptyState
        title="Metric pack UI coming soon"
        description="Configure evaluators and metric packs here. Use Runs to execute evaluations against your test set in the meantime."
      />
    </>
  );
}
