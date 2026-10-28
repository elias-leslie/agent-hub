/**
 * Message state update handlers for streaming events.
 */

import type { ChatMessage, ToolExecution, StreamMessage } from "../../types/chat";
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
          m.id === assistantId ? { ...m, ...routingFields(data), content: state.content, statusLabel: "Responding" } : m,
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
              agentProvider: provider,
              agentModel: data.model_display_name || data.model,
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
        };
        state.tools = [...state.tools, newTool];
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, toolExecutions: [...state.tools], statusLabel: `Running ${data.tool_name}` }
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

    case "error":
      throw new Error(data.error || "Unknown error");
  }
}
