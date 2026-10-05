"use client";

import { PageIntro } from "@/components/page-intro";
import { MetricsPackPage } from "@/features/metrics/metrics-pack-page";
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
      <MetricsPackPage projectId={projectId} />
    </>
  );
}
