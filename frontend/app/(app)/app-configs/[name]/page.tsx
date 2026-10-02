"use client";

import { useParams } from "next/navigation";
import { AppConfigFamilyDetail } from "@/features/app-configs/app-config-family-detail";
import { ProjectRequired } from "@/features/traces/project-required";
import { useProjectId } from "@/lib/project-store";

export default function AppConfigFamilyPage() {
  const params = useParams();
  const rawName = typeof params.name === "string" ? params.name : "";
  const familyName = rawName ? decodeURIComponent(rawName) : "";
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  if (!familyName) {
    return null;
  }

  return (
    <AppConfigFamilyDetail projectId={projectId} familyName={familyName} />
  );
}
