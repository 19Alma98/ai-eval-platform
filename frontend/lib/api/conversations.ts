import { apiGet, apiPost } from "@/lib/api/client";
import type { DatasetItem, LiveInteraction } from "@/lib/api/types";

export type ConversationSummary = {
  session_id: string;
  user_id: string | null;
  environment: string | null;
  turn_count: number;
  started_at: string;
  last_activity_at: string;
  conversation_id: string | null;
  judge_status: string | null;
  failing_score_kinds: string[];
};

export type ConversationTurn = {
  trace_id: string;
  start_time: string;
  question: string | null;
  answer: string | null;
  user_id: string | null;
  live_interaction_id: string | null;
  search_query: string | null;
};

export type ConversationScore = {
  id: string;
  kind: string;
  score: number | null;
  label: string | null;
  explanation: string | null;
  threshold: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type ConversationDetail = {
  summary: ConversationSummary;
  judge_status: string | null;
  turns: ConversationTurn[];
  scores: ConversationScore[];
  live_interactions: LiveInteraction[];
  session_judges_enabled: boolean;
};

export type ConversationListResult = {
  items: ConversationSummary[];
  session_judges_enabled: boolean;
};

export async function listConversations(
  projectId: string,
  params: {
    since?: string;
    until?: string;
    user_id?: string;
    environment?: string;
    search?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<ConversationListResult> {
  const qs = new URLSearchParams();
  if (params.since) qs.set("since", params.since);
  if (params.until) qs.set("until", params.until);
  if (params.user_id) qs.set("user_id", params.user_id);
  if (params.environment) qs.set("environment", params.environment);
  if (params.search) qs.set("search", params.search);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs}` : "";
  return apiGet<ConversationListResult>(
    `/api/v1/projects/${projectId}/conversations${suffix}`,
  );
}

export async function getConversation(
  projectId: string,
  sessionId: string,
): Promise<ConversationDetail> {
  return apiGet<ConversationDetail>(
    `/api/v1/projects/${projectId}/conversations/${encodeURIComponent(sessionId)}`,
  );
}

export async function scoreConversation(
  projectId: string,
  sessionId: string,
): Promise<ConversationDetail> {
  return apiPost<ConversationDetail>(
    `/api/v1/projects/${projectId}/conversations/${encodeURIComponent(sessionId)}/score`,
    {},
  );
}

export async function promoteConversation(
  projectId: string,
  sessionId: string,
  body: {
    dataset_id: string;
    expected_output: string;
    expected_doc_ids?: string[];
    mode?: "full" | "last_turn";
  },
): Promise<DatasetItem> {
  return apiPost<DatasetItem>(
    `/api/v1/projects/${projectId}/conversations/${encodeURIComponent(sessionId)}/promote`,
    body,
  );
}
