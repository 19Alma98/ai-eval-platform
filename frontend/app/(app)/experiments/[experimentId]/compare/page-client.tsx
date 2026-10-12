"use client";

import { useParams, usePathname } from "next/navigation";
import { PageIntro } from "@/components/page-intro";
import { ExperimentCompareView } from "@/features/experiments/experiment-compare-view";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";
import { resolveStaticExportParam } from "@/lib/static-export-params";

export default function ExperimentComparePage() {
  const params = useParams();
  const pathname = usePathname();
  const experimentId = resolveStaticExportParam(
    params.experimentId,
    pathname,
    /^\/experiments\/([^/]+)/,
  );
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
