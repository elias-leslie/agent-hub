/**
 * Session loading utilities.
 */

import type { ChatMessage } from "../../types/chat";
import type { SessionData } from "./types";

/**
 * Loads an existing chat session from the backend.
 */
export async function loadSession(
  sessionId: string,
  fetchFn: (url: string, options?: RequestInit) => Promise<Response>,
  sessionsEndpoint: string,
): Promise<ChatMessage[]> {
  const res = await fetchFn(`${sessionsEndpoint}/${sessionId}`);
  if (!res.ok) {
    throw new Error(`Failed to load session: ${res.status}`);
  }

  const session = (await res.json()) as SessionData;

  if (!session.messages || session.messages.length === 0) {
    return [];
  }

  return session.messages.map((m) => ({
    id: `loaded-${m.id}`,
    role: m.role as "user" | "assistant",
    content: m.content,
    timestamp: new Date(m.created_at),
    agentName: m.agent_name,
    agentModel: m.model_used,
  }));
}
