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

  const provider = session.provider as ChatMessage["agentProvider"];

  // Deduplicate messages — backend may have stored full history on each turn.
  // Keep first occurrence of each role+content pair to preserve chronological order.
  const seen = new Set<string>();
  const deduped = session.messages.filter((m) => {
    const key = `${m.role}:${m.content}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  return deduped.map((m) => ({
    id: `loaded-${m.id}`,
    role: m.role as "user" | "assistant",
    content: m.content,
    timestamp: new Date(m.created_at),
    agentName: m.agent_name,
    agentModel: m.model_used,
    ...(m.role === "assistant" && provider ? { agentProvider: provider } : {}),
  }));
}
