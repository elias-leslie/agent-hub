import type { ChatMessage } from "@agent-hub/chat-ui";
import type { PersonaStreamEntry } from "@/lib/api/persona-stream";
import type { FeedItem, FeedChildRun, FeedAnchor, FeedMessage, FeedHeartbeat } from "./workspace-types";

const NARRATION_TAG_RE = /\[\[P:[a-z_]+(?::[^\]]*?)?\]?\]?/g;
const APPLIED_CITATION_RE = /\s*(?:Applied:\s*)?\[(?:M|G|R):[a-f0-9]{3,8}[^\]]*\]?/g;
const FEEDBACK_RE = /\[\[F:[^\]]*\]?\]?/g;
const SUMMARY_RE = /\[\[S:[^\]]*\]?\]?/g;

function stripObservabilityTags(text: string): string {
  return text
    .replace(NARRATION_TAG_RE, "")
    .replace(APPLIED_CITATION_RE, "")
    .replace(FEEDBACK_RE, "")
    .replace(SUMMARY_RE, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

export function isChildRunItem(item: FeedItem): item is FeedChildRun {
  return item.kind === "child_run";
}

export function canAnchorChildRuns(item: FeedAnchor): item is FeedMessage | FeedHeartbeat {
  return item.kind !== "child_run";
}

export function buildChatMessage(entry: PersonaStreamEntry, personaDisplayName?: string): ChatMessage {
  return {
    id: entry.id,
    role: (entry.role as ChatMessage["role"]) || "assistant",
    content: entry.content ? stripObservabilityTags(entry.content) : "",
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
    message: message.role === "assistant" && personaDisplayName
      ? { ...message, agentName: message.agentName || personaDisplayName }
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
