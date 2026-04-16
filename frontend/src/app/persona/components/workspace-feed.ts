import type { ChatMessage } from "@agent-hub/chat-ui";
import type { PersonaStreamEntry } from "@/lib/api/persona-stream";
import type { FeedItem, FeedChildRun, FeedAnchor, FeedMessage, FeedHeartbeat } from "./workspace-types";
import { prettifyDisplayText } from "./workspace-format";

export function isChildRunItem(item: FeedItem): item is FeedChildRun {
  return item.kind === "child_run";
}

export function canAnchorChildRuns(item: FeedAnchor): item is FeedMessage | FeedHeartbeat {
  return item.kind !== "child_run";
}

export function buildChatMessage(entry: PersonaStreamEntry, personaDisplayName?: string): ChatMessage {
  const content = entry.content ? prettifyDisplayText(entry.content) || entry.content : "";
  return {
    id: entry.id,
    role: (entry.role as ChatMessage["role"]) || "assistant",
    content,
    timestamp: new Date(entry.timestamp),
    agentName: personaDisplayName || entry.agent_slug || undefined,
    agentModel: entry.model || undefined,
    agentProvider: "claude",
  };
}

export function buildLocalFeedMessages(messages: ChatMessage[], currentSessionId: string | null, personaDisplayName?: string): FeedItem[] {
  return messages.map((message) => ({
    kind: "message" as const,
    id: message.id,
    sessionId: currentSessionId,
    timestamp: message.timestamp,
    message: message.role === "assistant"
      ? {
          ...message,
          content: message.content ? prettifyDisplayText(message.content) || message.content : message.content,
          agentName: message.agentName || personaDisplayName,
        }
      : message,
  }));
}

export function buildRemoteFeedItems(entries: PersonaStreamEntry[], personaDisplayName?: string): FeedItem[] {
  return entries.map((entry) => {
    if (entry.entry_type === "message") {
      return {
        kind: "message" as const,
        id: entry.id,
        sessionId: entry.session_id,
        timestamp: new Date(entry.timestamp),
        message: buildChatMessage(entry, personaDisplayName),
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
