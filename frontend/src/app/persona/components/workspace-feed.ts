import type { ChatMessage } from "@agent-hub/chat-ui";
import type { PersonaStreamEntry } from "@/lib/api/persona-stream";
import type { FeedItem, FeedChildRun, FeedAnchor, FeedMessage, FeedHeartbeat } from "./workspace-types";

export function isChildRunItem(item: FeedItem): item is FeedChildRun {
  return item.kind === "child_run";
}

export function canAnchorChildRuns(item: FeedAnchor): item is FeedMessage | FeedHeartbeat {
  return item.kind !== "child_run";
}

export function buildChatMessage(entry: PersonaStreamEntry): ChatMessage {
  return {
    id: entry.id,
    role: (entry.role as ChatMessage["role"]) || "assistant",
    content: entry.content || "",
    timestamp: new Date(entry.timestamp),
    agentName: entry.agent_slug || undefined,
    agentModel: entry.model || undefined,
    agentProvider: "claude",
  };
}

export function buildLocalFeedMessages(messages: ChatMessage[], currentSessionId: string | null): FeedItem[] {
  return messages.map((message) => ({
    kind: "message" as const,
    id: message.id,
    sessionId: currentSessionId,
    timestamp: message.timestamp,
    message,
  }));
}

export function buildRemoteFeedItems(entries: PersonaStreamEntry[]): FeedItem[] {
  return entries.map((entry) => {
    if (entry.entry_type === "message") {
      return {
        kind: "message" as const,
        id: entry.id,
        sessionId: entry.session_id,
        timestamp: new Date(entry.timestamp),
        message: buildChatMessage(entry),
      };
    }
    return {
      kind: entry.entry_type,
      id: entry.id,
      sessionId: entry.session_id,
      timestamp: new Date(entry.timestamp),
      entry,
    };
  });
}
