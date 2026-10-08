"use client";

import { PageIntro } from "@/components/page-intro";
import { AppConfigList } from "@/features/app-configs/app-config-list";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";

export default function AppConfigsPage() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return (
    <>
      <PageIntro
        title="App configs"
        glossary="Versioned prompt, model, and retrieval bundles — pin aliases for experiments."
      />
      <AppConfigList />
    </>
  );
}
