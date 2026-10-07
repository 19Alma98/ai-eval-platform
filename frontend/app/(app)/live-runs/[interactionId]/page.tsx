"use client";

import { useParams } from "next/navigation";
import { PageIntro } from "@/components/page-intro";
import { LiveRunDetail } from "@/features/live-runs/live-run-detail";
import { ProjectRequired } from "@/features/traces/project-required";
import { useProjectId } from "@/lib/project-store";

export default function LiveRunDetailPage() {
  const params = useParams();
  const interactionId =
    typeof params.interactionId === "string" ? params.interactionId : "";
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
