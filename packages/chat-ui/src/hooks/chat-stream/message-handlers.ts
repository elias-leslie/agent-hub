/**
 * Message state update handlers for streaming events.
 */

import type { ChatMessage, ToolExecution, StreamMessage } from "../../types/chat";
import type { StreamState } from "./types";

function routePatch(data: StreamMessage, message: ChatMessage): Partial<ChatMessage> {
  return {
    routingMode: data.routing_mode ?? message.routingMode,
    workloadProfile: data.workload_profile ?? message.workloadProfile,
    routingDecisionId: data.routing_decision_id ?? message.routingDecisionId,
    autoCandidateModel: data.auto_candidate_model_id ?? message.autoCandidateModel,
    routingCanaryPercent: data.routing_canary_percent ?? message.routingCanaryPercent,
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
      if (
        data.routing_mode ||
        data.workload_profile ||
        data.routing_decision_id ||
        data.auto_candidate_model_id ||
        data.routing_canary_percent !== undefined
      ) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                ...m,
                ...routePatch(data, m),
              }
              : m,
          ),
        );
      }
      break;

    case "thinking":
      state.thinking += data.content || "";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, thinking: state.thinking, statusLabel: "Thinking" } : m,
        ),
      );
      break;

    case "content":
      state.content += data.content || "";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId ? { ...m, content: state.content, statusLabel: "Responding" } : m,
        ),
      );
      break;

    case "done":
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
              ...m,
              content: state.content,
              thinking: state.thinking || undefined,
              agentProvider: provider,
              agentName: data.agent_used || m.agentName,
              agentModel: data.model_display_name || data.model,
              inputTokens: data.input_tokens,
              outputTokens: data.output_tokens,
              thinkingTokens: data.thinking_tokens,
              truncated: data.was_truncated,
              maxTokensRequested: data.max_tokens_requested,
              modelLimit: data.model_limit,
              truncationWarning: data.truncation_warning,
              ...routePatch(data, m),
              statusLabel: "Complete",
            }
            : m,
        ),
      );
      break;

    case "cancelled":
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
              ...m,
              content: state.content,
              thinking: state.thinking || undefined,
              agentProvider: provider,
              agentModel: data.model,
              cancelled: true,
              inputTokens: data.input_tokens,
              outputTokens: data.output_tokens,
              thinkingTokens: data.thinking_tokens,
              ...routePatch(data, m),
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

    case "error":
      throw new Error(data.error || "Unknown error");
  }
}
