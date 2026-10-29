/**
 * Message state update handlers for streaming events.
 */

import type { ChatCompaction, ChatMessage, ToolExecution, StreamMessage } from "../../types/chat";
import type { StreamState } from "./types";

/** Which model was asked for and which answered, once the event carries them. */
function routingFields(data: StreamMessage): Partial<ChatMessage> {
  return {
    ...(data.model ? { requestedModel: data.model } : {}),
    ...(data.model_used ? { servedModel: data.model_used } : {}),
    ...(data.agent_used ? { agentName: data.agent_used } : {}),
    ...(data.fallback_used !== undefined ? { fallbackUsed: data.fallback_used } : {}),
    ...(data.fallback_reason ? { fallbackReason: data.fallback_reason } : {}),
  };
}

const numberOrUndefined = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isFinite(value) ? value : undefined;

/** The compaction a `context_compacted` event reports. A size the event lacks stays absent. */
function compactionFromEvent(data: StreamMessage): ChatCompaction {
  const model = data.summarizer_model;
  return {
    status: data.status === "failed" ? "failed" : "ok",
    ...(numberOrUndefined(data.tokens_before) !== undefined ? { tokensBefore: data.tokens_before } : {}),
    ...(numberOrUndefined(data.tokens_after) !== undefined ? { tokensAfter: data.tokens_after } : {}),
    ...(numberOrUndefined(data.messages_summarized) !== undefined ? { messagesSummarized: data.messages_summarized } : {}),
    ...(typeof model === "string" && model ? { summarizerModel: model } : {}),
    ...(numberOrUndefined(data.cost_usd) !== undefined ? { costUsd: data.cost_usd as number } : {}),
  };
}

function sameCompaction(a: ChatCompaction | undefined, b: ChatCompaction): boolean {
  return a !== undefined && a.status === b.status && a.tokensBefore === b.tokensBefore && a.tokensAfter === b.tokensAfter;
}

/**
 * Handles incoming stream events and updates message state accordingly.
 */
export function handleStreamEvent(
  data: StreamMessage,
  assistantId: string,
  state: StreamState,
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
  setCurrentSessionId: React.Dispatch<React.SetStateAction<string | null>>,
): void {
  const provider = data.provider as ChatMessage["agentProvider"];

  // Time the model spends thinking: a stretch opens at its first thinking event and closes at the next event of another kind.
  const now = Date.now();
  if (data.type === "thinking") {
    state.thinkingSince ??= now;
  } else if (state.thinkingSince != null && data.type !== "connected") {
    state.thinkingMs = (state.thinkingMs ?? 0) + (now - state.thinkingSince);
    state.thinkingSince = null;
  }
  const thinkingMs = state.thinkingMs !== undefined && state.thinkingMs > 0 ? state.thinkingMs : undefined;

  switch (data.type) {
    case "connected":
      if (data.session_id) {
        setCurrentSessionId(data.session_id);
      }
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, ...routingFields(data) } : m)));
      break;

    case "thinking":
      state.thinking += data.content || "";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, ...routingFields(data), thinking: state.thinking, statusLabel: "Thinking" } : m,
        ),
      );
      break;

    case "content":
      state.content += data.content || "";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, ...routingFields(data), content: state.content, thinkingMs, statusLabel: "Responding" }
            : m,
        ),
      );
      break;

    case "done":
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
              ...m,
              ...routingFields(data),
              content: state.content,
              thinking: state.thinking || undefined,
              thinkingMs,
              agentProvider: provider,
              agentModel: data.model_display_name || data.model,
              ...(typeof data.cost_usd === "number" ? { costUsd: data.cost_usd } : {}),
              inputTokens: data.input_tokens,
              outputTokens: data.output_tokens,
              thinkingTokens: data.thinking_tokens,
              truncated: data.was_truncated,
              maxTokensRequested: data.max_tokens_requested,
              modelLimit: data.model_limit,
              truncationWarning: data.truncation_warning,
              statusLabel: "Complete",
            }
            : m,
        ),
      );
      break;

    case "cancelled":
    case "cancel_acknowledged":
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
              ...m,
              content: state.content,
              thinking: state.thinking || undefined,
              agentProvider: provider ?? m.agentProvider,
              agentModel: data.model ?? m.agentModel,
              cancelled: true,
              inputTokens: data.input_tokens,
              outputTokens: data.output_tokens,
              thinkingTokens: data.thinking_tokens,
              statusLabel: "Cancelled",
            }
            : m,
        ),
      );
      break;

    case "tool_use":
      if (data.tool_id && data.tool_name) {
        const newTool: ToolExecution = {
          id: data.tool_id,
          name: data.tool_name,
          input: data.tool_input || {},
          status: "running",
          startedAt: new Date(),
          contentOffset: state.content.length,
        };
        state.tools = [...state.tools, newTool];
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, toolExecutions: [...state.tools], thinkingMs, statusLabel: `Running ${data.tool_name}` }
              : m,
          ),
        );
      }
      break;

    case "tool_start":
      // Granular event: backend has begun executing this tool
      if (data.tool_id) {
        state.tools = state.tools.map((tool) =>
          tool.id === data.tool_id
            ? { ...tool, startedAt: new Date() }
            : tool,
        );
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, toolExecutions: [...state.tools], statusLabel: "Running tool" }
              : m,
          ),
        );
      }
      break;

    case "tool_result":
      if (data.tool_id) {
        state.tools = state.tools.map((tool) =>
          tool.id === data.tool_id
            ? {
              ...tool,
              status: data.tool_status || "complete",
              result: data.tool_result,
              completedAt: new Date(),
            }
            : tool,
        );
        // The next model turn starts after its tools' results.
        state.turnStart = { content: state.content.length, thinking: state.thinking.length, tools: state.tools.length };
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                ...m,
                toolExecutions: [...state.tools],
                statusLabel: data.tool_status === "error" ? "Tool failed" : "Tool complete",
              }
              : m,
          ),
        );
      }
      break;

    case "turn_retry": {
      // The backend dropped an interrupted model turn and is re-running it: drop its partial output too.
      const start = state.turnStart ?? { content: 0, thinking: 0, tools: 0 };
      state.content = state.content.slice(0, start.content);
      state.thinking = state.thinking.slice(0, start.thinking);
      state.tools = state.tools.slice(0, start.tools);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
              ...m,
              content: state.content,
              thinking: state.thinking || undefined,
              toolExecutions: [...state.tools],
              retries: [...(m.retries ?? []), { attempt: data.attempt, max: data.max_retries, reason: data.reason }],
              statusLabel: `Retrying (${data.attempt ?? "?"}/${data.max_retries ?? "?"})`,
            }
            : m,
        ),
      );
      break;
    }

    case "context_compacted": {
      // The history was summarized; the answer is not changed. The note goes just above the answer being written.
      const compaction = compactionFromEvent(data);
      setMessages((prev) => {
        // A rejoined turn replays its events from the start, and the session read may already hold this note.
        if (prev.some((m) => m.kind === "compaction" && sameCompaction(m.compaction, compaction))) return prev;
        const note: ChatMessage = {
          id: `compaction-${data.seq ?? prev.length}-${compaction.tokensBefore ?? ""}-${compaction.tokensAfter ?? ""}`,
          role: "system",
          kind: "compaction",
          compaction,
          content: "",
          timestamp: new Date(),
        };
        const at = prev.findIndex((m) => m.id === assistantId);
        return at < 0 ? [...prev, note] : [...prev.slice(0, at), note, ...prev.slice(at)];
      });
      break;
    }

    case "error":
      throw new Error(data.error || "Unknown error");
  }
}
