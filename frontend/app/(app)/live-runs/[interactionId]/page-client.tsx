"use client";

import { useParams, usePathname } from "next/navigation";
import { PageIntro } from "@/components/page-intro";
import { LiveRunDetail } from "@/features/live-runs/live-run-detail";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";
import { resolveStaticExportParam } from "@/lib/static-export-params";

export default function LiveRunDetailPage() {
  const params = useParams();
  const pathname = usePathname();
  const interactionId = resolveStaticExportParam(
    params.interactionId,
    pathname,
    /^\/live-runs\/([^/]+)/,
  );
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  if (!interactionId) {
    return null;
  }

  return (
    <>
      <PageIntro
        title="Live interaction"
        glossary="Question, answer, retrieved documents, judge scores, and review actions."
      />
      <LiveRunDetail interactionId={interactionId} />
    </>
  );
}
