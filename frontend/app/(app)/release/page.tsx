"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { PageIntro } from "@/components/page-intro";
import { LoadingBlock } from "@/components/loading-block";
import { ReleaseCheckForm } from "@/features/release/release-check-form";
import { ProjectRequired } from "@/features/traces/project-required";
import { useProjectId } from "@/lib/project-store";

function ReleasePageContent() {
  const { projectId } = useProjectId();
  const searchParams = useSearchParams();
  const experimentFromQuery = searchParams.get("experiment") ?? "";

  if (!projectId) {
    return <ProjectRequired />;
  }

  return (
    <>
      <PageIntro
        title="Release"
        glossary="PASS/FAIL against YAML thresholds — whether to ship."
      />
      <ReleaseCheckForm
        projectId={projectId}
        initialExperimentId={experimentFromQuery}
      />
    </>
  );
}

export default function ReleasePage() {
  return (
    <Suspense fallback={<LoadingBlock className="min-h-[240px]" />}>
      <ReleasePageContent />
    </Suspense>
  );
}
