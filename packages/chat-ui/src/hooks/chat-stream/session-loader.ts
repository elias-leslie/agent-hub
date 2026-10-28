/**
 * Session loading utilities.
 */

import type { ChatHubClient } from "../../client";
import type { ChatMessage, ToolExecution } from "../../types/chat";
import type { SessionToolExecution } from "./types";

export interface LoadedSession {
  messages: ChatMessage[];
  projectId: string | null;
  /** `running` when the server is still working on a turn for this session. */
  turnState: "running" | "idle";
  /** Where the running turn is (`thinking`, `responding`, `running_tool:name`, ...). */
  turnPhase: string | null;
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
 * Loads an existing chat session through the client.
 */
export async function loadSession(client: Pick<ChatHubClient, "sessions">, sessionId: string): Promise<LoadedSession> {
  const session = await client.sessions.get(sessionId);
  const turnState = session.turn_state === "running" ? "running" : "idle";
  const turnPhase = turnState === "running" ? (session.turn_phase ?? null) : null;

  if (!session.messages || session.messages.length === 0) {
    return {
      messages: [],
      projectId: session.project_id ?? null,
      turnState,
      turnPhase,
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
  const seenToolExecutionIds = new Set<string>();
  const uniqueToolExecutionsByMessage = new Map<string | number, SessionToolExecution[]>();
  for (const message of [...deduped].reverse()) {
    const uniqueTools = ((message.tool_executions ?? []) as SessionToolExecution[]).filter((tool) => {
      if (seenToolExecutionIds.has(tool.id)) return false;
      seenToolExecutionIds.add(tool.id);
      return true;
    });
    if (uniqueTools.length > 0) {
      uniqueToolExecutionsByMessage.set(message.id, uniqueTools);
    }
  }

  // The session names the route of its latest turn; only that turn's answer carries it.
  const lastAssistantId = [...deduped].reverse().find((m) => m.role === "assistant")?.id;
  const latestRoute: Partial<ChatMessage> = {
    ...(session.requested_model ? { requestedModel: session.requested_model } : {}),
    ...(session.fallback_used !== undefined ? { fallbackUsed: session.fallback_used } : {}),
  };

  return {
    messages: deduped.map((m) => ({
      id: `loaded-${m.id}`,
      role: m.role as "user" | "assistant" | "system",
      content: m.content ?? "",
      timestamp: new Date(m.created_at),
      agentName: m.agent_display_name || m.agent_name || undefined,
      agentModel: m.model_display_name || m.model_used || undefined,
      ...(m.role === "assistant" && provider ? { agentProvider: provider } : {}),
      ...(m.role === "assistant" && m.model_used ? { servedModel: m.model_used } : {}),
      ...(m.id === lastAssistantId ? latestRoute : {}),
      ...(m.thinking ? { thinking: m.thinking } : {}),
      ...(m.thinking_tokens ? { thinkingTokens: m.thinking_tokens } : {}),
      ...(uniqueToolExecutionsByMessage.has(m.id)
        ? { toolExecutions: mapToolExecutions(uniqueToolExecutionsByMessage.get(m.id)) }
        : {}),
    })),
    projectId: session.project_id ?? null,
    turnState,
    turnPhase,
  };
}
