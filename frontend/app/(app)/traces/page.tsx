"use client";

import { PageIntro } from "@/components/page-intro";
import { TraceList } from "@/features/traces/trace-list";
import { ProjectRequired } from "@/features/traces/project-required";
import { useProjectId } from "@/lib/project-store";

export default function TracesPage() {
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  return (
    <>
      <PageIntro
        title="Traces"
        glossary="Real application runs (latency, errors, I/O) — telemetry, not quality scores."
      />
      <TraceList />
    </>
  );
}
