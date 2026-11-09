"use client";

import { useParams, usePathname } from "next/navigation";
import { ConversationDetail } from "@/features/conversations/conversation-detail";
import { ProjectRequired } from "@/components/project-required";
import { useProjectId } from "@/lib/project-store";
import { resolveStaticExportParam } from "@/lib/static-export-params";

export default function ConversationDetailPage() {
  const params = useParams();
  const pathname = usePathname();
  const rawSessionId = resolveStaticExportParam(
    params.sessionId,
    pathname,
    /^\/conversations\/([^/]+)/,
  );
  const sessionId = rawSessionId ? decodeURIComponent(rawSessionId) : "";
  const { projectId } = useProjectId();

  if (!projectId) {
    return <ProjectRequired />;
  }

  if (!sessionId) {
    return null;
  }

  return <ConversationDetail sessionId={sessionId} />;
}
