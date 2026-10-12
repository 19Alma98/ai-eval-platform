"use client";

import { useParams, usePathname } from "next/navigation";
import { AppConfigFamilyDetail } from "@/features/app-configs/app-config-family-detail";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";
import { resolveStaticExportParam } from "@/lib/static-export-params";

export default function AppConfigFamilyPage() {
  const params = useParams();
  const pathname = usePathname();
  const rawName = resolveStaticExportParam(
    params.name,
    pathname,
    /^\/app-configs\/([^/]+)/,
  );
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
