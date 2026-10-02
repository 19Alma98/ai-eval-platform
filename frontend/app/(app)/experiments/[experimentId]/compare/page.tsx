"use client";

import { useParams } from "next/navigation";
import { PageIntro } from "@/components/page-intro";
import { ExperimentCompareView } from "@/features/experiments/experiment-compare-view";
import { ProjectRequired } from "@/features/traces/project-required";
import { useProjectId } from "@/lib/project-store";

export default function ExperimentComparePage() {
  const params = useParams();
  const experimentId =
    typeof params.experimentId === "string" ? params.experimentId : "";
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  if (!experimentId) {
    return null;
  }

  return (
    <>
      <PageIntro
        title="Compare"
        glossary="Deltas vs a baseline experiment — better/worse on shared metrics."
      />
      <ExperimentCompareView
        projectId={projectId}
        experimentId={experimentId}
      />
    </>
  );
}
