"use client";

import { PageIntro } from "@/components/page-intro";
import { DatasetList } from "@/features/datasets/dataset-list";
import { ProjectRequired } from "@/features/traces/project-required";
import { useProjectId } from "@/lib/project-store";

export default function DatasetsPage() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return (
    <>
      <PageIntro
        title="Datasets"
        glossary="Reusable test cases (input + expected/actual) — the suite you measure against."
      />
      <DatasetList />
    </>
  );
}
