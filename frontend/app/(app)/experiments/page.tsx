"use client";

import { PageIntro } from "@/components/page-intro";
import { ExperimentList } from "@/features/experiments/experiment-list";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";

export default function ExperimentsPage() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return (
    <>
      <PageIntro
        title="Runs"
        glossary="An evaluation run on a dataset — scores per evaluator (quality / latency / cost…)."
      />
      <ExperimentList />
    </>
  );
}
