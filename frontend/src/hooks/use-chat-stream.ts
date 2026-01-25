"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ChatMessage,
  StreamStatus,
  ToolExecution,
} from "@/types/chat";
import { INTERNAL_HEADERS, getApiBaseUrl, fetchApi } from "@/lib/api-config";

const DEFAULT_MODEL = "claude-sonnet-4-5-20250514";

function formatModelName(modelId: string): string {
  const modelNames: Record<string, string> = {
    "claude-sonnet-4-5-20250514": "Claude Sonnet 4.5",
    "claude-sonnet-4-5": "Claude Sonnet 4.5",
    "claude-opus-4-5-20250514": "Claude Opus 4.5",
    "claude-opus-4-5": "Claude Opus 4.5",
    "claude-haiku-4-5-20250514": "Claude Haiku 4.5",
    "claude-haiku-4-5": "Claude Haiku 4.5",
    "gemini-3-flash-preview": "Gemini 3 Flash",
    "gemini-3-pro-preview": "Gemini 3 Pro",
  };
  return modelNames[modelId] || modelId;
}

interface UseChatStreamOptions {
  model?: string;
  sessionId?: string;
  temperature?: number;
  /** Working directory for tool execution (enables coding agent mode) */
  workingDir?: string;
  /** Enable tool calling for coding agent mode */
  toolsEnabled?: boolean;
}

interface UseChatStreamReturn {
  messages: ChatMessage[];
  status: StreamStatus;
  error: string | null;
  currentSessionId: string | null;
  sendMessage: (content: string, targetModels?: string[]) => void;
  cancelStream: () => void;
  clearMessages: () => void;
  editMessage: (messageId: string, newContent: string) => void;
  regenerateMessage: (messageId: string) => void;
}

/**
 * Hook for managing chat streaming with SSE and cancellation support.
 */
export function useChatStream(
  options: UseChatStreamOptions = {},
): UseChatStreamReturn {
  const {
    model = DEFAULT_MODEL,
    sessionId,
    temperature = 1.0,
    workingDir,
    toolsEnabled = false,
  } = options;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);

  const abortControllersRef = useRef<AbortController[]>([]);
  const streamStatesRef = useRef<Map<string, { content: string; thinking: string; tools: ToolExecution[] }>>(new Map());
  const statusRef = useRef<StreamStatus>(status);
  statusRef.current = status;

  const generateId = () =>
    `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

  // Load existing messages when sessionId is provided
  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      setCurrentSessionId(null);
      return;
    }

    const loadSession = async () => {
      try {
        setStatus("connecting");
        const res = await fetchApi(`${getApiBaseUrl()}/api/sessions/${sessionId}`);
        if (!res.ok) {
          throw new Error(`Failed to load session: ${res.status}`);
        }
        const session = await res.json();
        setCurrentSessionId(session.id);

        if (session.messages && session.messages.length > 0) {
          const loadedMessages: ChatMessage[] = session.messages.map(
            (m: { id: number; role: string; content: string; created_at: string; agent_name?: string }) => ({
              id: `loaded-${m.id}`,
              role: m.role as "user" | "assistant",
              content: m.content,
              timestamp: new Date(m.created_at),
              agentName: m.agent_name,
            })
          );
          setMessages(loadedMessages);
        }
        setStatus("idle");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load session");
        setStatus("error");
      }
    };

    loadSession();
  }, [sessionId]);

  const sendMessage = useCallback(
    async (content: string, targetModels?: string[]) => {
      if (status !== "idle") return;

      setError(null);
      setStatus("connecting");

      const effectiveModels = targetModels && targetModels.length > 0 ? targetModels : [model];

      // Add user message immediately
      const userMessage: ChatMessage = {
        id: generateId(),
        role: "user",
        content,
        timestamp: new Date(),
        targetModel: effectiveModels[0],
      };
      setMessages((prev) => [...prev, userMessage]);

      // Create placeholder messages for each model
      const responseGroupId = effectiveModels.length > 1 ? generateId() : undefined;
      const assistantIds: string[] = [];

      for (const targetModel of effectiveModels) {
        const assistantId = generateId();
        assistantIds.push(assistantId);
        streamStatesRef.current.set(assistantId, { content: "", thinking: "", tools: [] });

        const assistantMessage: ChatMessage = {
          id: assistantId,
          role: "assistant",
          content: "",
          timestamp: new Date(),
          toolExecutions: toolsEnabled ? [] : undefined,
          responseGroupId,
          agentModel: targetModel,
        };
        setMessages((prev) => [...prev, assistantMessage]);
      }

      // Build message history for context
      const messageHistory = messages.map((m) => {
        if (m.role === "assistant" && m.agentModel) {
          const modelName = formatModelName(m.agentModel);
          return {
            role: m.role,
            content: `[${modelName}]: ${m.content}`,
          };
        }
        return {
          role: m.role,
          content: m.content,
        };
      });
      messageHistory.push({ role: "user", content });

      // Create abort controllers for each stream
      const controllers = effectiveModels.map(() => new AbortController());
      abortControllersRef.current = controllers;

      const streamForModel = async (targetModel: string, assistantId: string, controller: AbortController) => {
        const requestBody = {
          model: targetModel,
          messages: messageHistory,
          temperature,
          session_id: sessionId,
          working_dir: workingDir,
          tools_enabled: toolsEnabled,
          project_id: "agent-hub",
          stream: true,
        };

        const response = await fetch("/api/complete", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...INTERNAL_HEADERS,
          },
          body: JSON.stringify(requestBody),
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        if (!response.body) {
          throw new Error("No response body");
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        const state = streamStatesRef.current.get(assistantId)!;

        while (true) {
          const { done, value } = await reader.read();

          if (done) break;

          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split("\n");

          for (const line of lines) {
            if (!line.trim() || !line.startsWith("data: ")) continue;

            const dataStr = line.slice(6);
            if (dataStr === "[DONE]") break;

            try {
              const data = JSON.parse(dataStr);

              switch (data.type) {
                case "connected":
                  if (data.session_id) {
                    setCurrentSessionId(data.session_id);
                  }
                  break;

                case "thinking":
                  state.thinking += data.content || "";
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId
                        ? { ...m, thinking: state.thinking }
                        : m,
                    ),
                  );
                  break;

                case "content":
                  state.content += data.content || "";
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === assistantId
                        ? { ...m, content: state.content }
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
                            content: state.content,
                            thinking: state.thinking || undefined,
                            agentProvider: data.provider,
                            agentModel: data.model,
                            inputTokens: data.input_tokens,
                            outputTokens: data.output_tokens,
                            thinkingTokens: data.thinking_tokens,
                            truncated: data.was_truncated,
                            maxTokensRequested: data.max_tokens_requested,
                            modelLimit: data.model_limit,
                            truncationWarning: data.truncation_warning,
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
                            agentProvider: data.provider,
                            agentModel: data.model,
                            cancelled: true,
                            inputTokens: data.input_tokens,
                            outputTokens: data.output_tokens,
                            thinkingTokens: data.thinking_tokens,
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
                          ? { ...m, toolExecutions: [...state.tools] }
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
                          ? { ...m, toolExecutions: [...state.tools] }
                          : m,
                      ),
                    );
                  }
                  break;

                case "error":
                  throw new Error(data.error || "Unknown error");
              }
            } catch (parseError) {
              console.warn("Failed to parse SSE data:", dataStr, parseError);
            }
          }
        }
      };

      try {
        setStatus("streaming");

        await Promise.all(
          effectiveModels.map((targetModel, index) =>
            streamForModel(targetModel, assistantIds[index], controllers[index])
          )
        );

        setStatus("idle");
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") {
          setStatus("idle");
        } else {
          setError(err instanceof Error ? err.message : "Stream connection error");
          setStatus("error");
        }
      } finally {
        abortControllersRef.current = [];
        streamStatesRef.current.clear();
      }
    },
    [messages, model, temperature, sessionId, status, workingDir, toolsEnabled],
  );

  const cancelStream = useCallback(() => {
    if (status !== "streaming" || abortControllersRef.current.length === 0) return;

    setStatus("cancelling");
    abortControllersRef.current.forEach((controller) => controller.abort());
  }, [status]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
    setStatus("idle");
  }, []);

  const editMessage = useCallback((messageId: string, newContent: string) => {
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id === messageId) {
          const previousVersions = m.previousVersions || [];
          return {
            ...m,
            content: newContent,
            edited: true,
            editedAt: new Date(),
            previousVersions: [...previousVersions, m.content],
          };
        }
        return m;
      }),
    );
  }, []);

  const regenerateMessage = useCallback(
    (messageId: string) => {
      const messageIndex = messages.findIndex((m) => m.id === messageId);
      if (messageIndex === -1 || status !== "idle") return;

      let userMessageIndex = messageIndex - 1;
      while (
        userMessageIndex >= 0 &&
        messages[userMessageIndex].role !== "user"
      ) {
        userMessageIndex--;
      }
      if (userMessageIndex < 0) return;

      const userMessage = messages[userMessageIndex];
      setMessages((prev) => prev.slice(0, messageIndex));

      setTimeout(() => {
        sendMessage(userMessage.content);
      }, 100);
    },
    [messages, status, sendMessage],
  );

  return {
    messages,
    status,
    error,
    currentSessionId,
    sendMessage,
    cancelStream,
    clearMessages,
    editMessage,
    regenerateMessage,
  };
}
