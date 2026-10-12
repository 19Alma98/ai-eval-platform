"use client";

import { AppConfigList } from "@/features/app-configs/app-config-list";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";

export default function AppConfigsPage() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return <AppConfigList />;
}
