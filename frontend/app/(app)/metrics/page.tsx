"use client";

import { PageIntro } from "@/components/page-intro";
import { MetricsSetList } from "@/features/metrics/metrics-set-list";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";

export default function MetricsPage() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return (
    <>
      <PageIntro
        title="Metrics"
        glossary="Evaluator packs and thresholds — what you measure on each test set run."
      />
      <MetricsSetList projectId={projectId} />
    </>
  );
}
