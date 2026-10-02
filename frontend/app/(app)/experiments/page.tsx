"use client";

import { PageIntro } from "@/components/page-intro";
import { ExperimentList } from "@/features/experiments/experiment-list";
import { ProjectRequired } from "@/features/traces/project-required";
import { useProjectId } from "@/lib/project-store";

export default function ExperimentsPage() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return (
    <>
      <PageIntro
        title="Experiments"
        glossary="An evaluation run on a dataset — scores per evaluator (quality / latency / cost…)."
      />
      <ExperimentList />
    </>
  );
}
