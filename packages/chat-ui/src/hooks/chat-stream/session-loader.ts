/**
 * Session loading utilities.
 */

import type { ChatMessage, ToolExecution } from "../../types/chat";
import type { SessionData, SessionToolExecution } from "./types";

export interface LoadedSession {
  messages: ChatMessage[];
  projectId: string | null;
}

function mapToolExecutions(
  tools: SessionToolExecution[] | undefined,
): ToolExecution[] | undefined {
  if (!tools || tools.length === 0) return undefined;
  return tools.map((t) => ({
    id: t.id,
    name: t.name,
    input: (t.input as Record<string, unknown>) ?? {},
    status: (t.status as ToolExecution["status"]) || "complete",
    result: t.result ?? undefined,
    startedAt: new Date(),
    completedAt: new Date(),
  }));
}

/**
 * Loads an existing chat session from the backend.
 */
export async function loadSession(
  sessionId: string,
  fetchFn: (url: string, options?: RequestInit) => Promise<Response>,
  sessionsEndpoint: string,
): Promise<LoadedSession> {
  const res = await fetchFn(`${sessionsEndpoint}/${sessionId}`);
  if (!res.ok) {
    throw new Error(`Failed to load session: ${res.status}`);
  }

  const session = (await res.json()) as SessionData;

  if (!session.messages || session.messages.length === 0) {
    return {
      messages: [],
      projectId: session.project_id ?? null,
    };
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

  return {
    messages: deduped.map((m) => ({
      id: `loaded-${m.id}`,
      role: m.role as "user" | "assistant" | "system",
      content: m.content,
      timestamp: new Date(m.created_at),
      agentName: m.agent_display_name || m.agent_name,
      agentModel: m.model_display_name || m.model_used,
      ...(m.role === "assistant" && provider ? { agentProvider: provider } : {}),
      ...(m.thinking ? { thinking: m.thinking } : {}),
      ...(m.thinking_tokens ? { thinkingTokens: m.thinking_tokens } : {}),
      ...(m.tool_executions && m.tool_executions.length > 0
        ? { toolExecutions: mapToolExecutions(m.tool_executions) }
        : {}),
    })),
    projectId: session.project_id ?? null,
  };
}
