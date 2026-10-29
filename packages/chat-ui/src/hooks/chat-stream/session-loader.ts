/**
 * Session loading utilities.
 */

import type { ChatHubClient } from "../../client";
import type { ChatCompaction, ChatMessage, ToolExecution } from "../../types/chat";
import type { SessionToolExecution } from "./types";

/**
 * What the session read says about the whole conversation. A field the server did not report is absent: never 0.
 */
export interface SessionStats {
  inputTokens?: number;
  outputTokens?: number;
  /** What the session's model calls cost, when the server logged any. */
  costUsd?: number;
  /** 0-100, only when the server measured it for the latest request. */
  contextPercent?: number;
  branch?: string;
}

export interface LoadedSession {
  stats: SessionStats;
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
    ...(typeof t.content_offset === "number" ? { contentOffset: t.content_offset } : {}),
  }));
}

const num = (value: unknown): number | undefined => {
  const n = typeof value === "number" ? value : Number.NaN;
  return Number.isFinite(n) ? n : undefined;
};

/** The compaction record a stored `compaction` message carries (the server's field names); null when it carries none. */
function readCompaction(record: unknown): ChatCompaction | null {
  if (!record || typeof record !== "object") return null;
  const r = record as Record<string, unknown>;
  const model = r.summarizer_model;
  return {
    status: r.status === "failed" ? "failed" : "ok",
    ...(num(r.tokens_before) !== undefined ? { tokensBefore: num(r.tokens_before) } : {}),
    ...(num(r.tokens_after) !== undefined ? { tokensAfter: num(r.tokens_after) } : {}),
    ...(num(r.messages_summarized) !== undefined ? { messagesSummarized: num(r.messages_summarized) } : {}),
    ...(typeof model === "string" && model ? { summarizerModel: model } : {}),
    ...(num(r.cost_usd) !== undefined ? { costUsd: num(r.cost_usd) } : {}),
  };
}

/** The usage, context and branch a session read carries. Zero tokens mean no usage reported, not a free session. */
export function readSessionStats(session: Awaited<ReturnType<ChatHubClient["sessions"]["get"]>>): SessionStats {
  const input = Number(session.total_input_tokens);
  const output = Number(session.total_output_tokens);
  const usage = (session as { context_usage?: { percent_used?: unknown; measured?: unknown } | null }).context_usage;
  const percent = Number(usage?.percent_used);
  const branch = (session as { current_branch?: unknown }).current_branch;
  const cost = Number(session.total_cost_usd);
  const hasTokens = (Number.isFinite(input) && input > 0) || (Number.isFinite(output) && output > 0);
  return {
    ...(hasTokens && Number.isFinite(input) && input > 0 ? { inputTokens: input } : {}),
    ...(hasTokens && Number.isFinite(output) && output > 0 ? { outputTokens: output } : {}),
    ...(session.total_cost_usd != null && Number.isFinite(cost) && cost > 0 ? { costUsd: cost } : {}),
    ...(usage && usage.measured !== false && Number.isFinite(percent) ? { contextPercent: Math.min(100, Math.max(0, percent)) } : {}),
    ...(typeof branch === "string" && branch ? { branch } : {}),
  };
}

/**
 * Loads an existing chat session through the client.
 */
export async function loadSession(client: Pick<ChatHubClient, "sessions">, sessionId: string): Promise<LoadedSession> {
  const session = await client.sessions.get(sessionId);
  const turnState = session.turn_state === "running" ? "running" : "idle";
  const turnPhase = turnState === "running" ? (session.turn_phase ?? null) : null;

  const stats = readSessionStats(session);

  if (!session.messages || session.messages.length === 0) {
    return {
      stats,
      messages: [],
      projectId: session.project_id ?? null,
      turnState,
      turnPhase,
    };
  }

  const provider = session.provider as ChatMessage["agentProvider"];

  // The same stored message listed twice is shown once. Two messages with identical text are different turns
  // (different ids) and both stay: never match on role or text.
  const seenMessageIds = new Set<string>();
  const deduped = session.messages.filter((m) => {
    const key = String(m.id);
    if (seenMessageIds.has(key)) return false;
    seenMessageIds.add(key);
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
    stats,
    messages: deduped.map((m) => ({
      id: `loaded-${m.id}`,
      role: m.role as "user" | "assistant" | "system",
      content: m.content ?? "",
      timestamp: new Date(m.created_at),
      ...(m.kind === "compaction" && readCompaction(m.compaction)
        ? { kind: "compaction" as const, compaction: readCompaction(m.compaction) as ChatCompaction }
        : {}),
      ...(m.kind === "incomplete_turn" ? { incomplete: true } : {}),
      agentName: m.agent_display_name || m.agent_name || undefined,
      agentModel: m.model_display_name || m.model_used || undefined,
      ...(m.role === "assistant" && provider ? { agentProvider: provider } : {}),
      ...(m.role === "assistant" && m.model_used ? { servedModel: m.model_used } : {}),
      ...(m.id === lastAssistantId ? latestRoute : {}),
      ...(m.thinking ? { thinking: m.thinking } : {}),
      ...(m.thinking_tokens ? { thinkingTokens: m.thinking_tokens } : {}),
      ...(m.thinking_ms ? { thinkingMs: m.thinking_ms } : {}),
      ...(uniqueToolExecutionsByMessage.has(m.id)
        ? { toolExecutions: mapToolExecutions(uniqueToolExecutionsByMessage.get(m.id)) }
        : {}),
    })),
    projectId: session.project_id ?? null,
    turnState,
    turnPhase,
  };
}
