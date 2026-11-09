import { ConversationDetail } from "@/features/conversations/conversation-detail";

export default async function ConversationDetailPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  return <ConversationDetail sessionId={decodeURIComponent(sessionId)} />;
}
