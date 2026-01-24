"use client";

import { useCallback, useRef, useState } from "react";
import type {
  ChatMessage,
  StreamStatus,
  ToolExecution,
} from "@/types/chat";
import { INTERNAL_HEADERS } from "@/lib/api-config";

const DEFAULT_MODEL = "claude-sonnet-4-5-20250514";

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
  sendMessage: (content: string) => void;
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

  const abortControllerRef = useRef<AbortController | null>(null);
  const currentMessageRef = useRef<string>("");
  const currentThinkingRef = useRef<string>("");
  const currentMessageIdRef = useRef<string>("");
  const currentToolExecutionsRef = useRef<ToolExecution[]>([]);
  const statusRef = useRef<StreamStatus>(status);
  statusRef.current = status;

  const generateId = () =>
    `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

  const sendMessage = useCallback(
    async (content: string) => {
      if (status !== "idle") return;

      setError(null);
      setStatus("connecting");

      // Add user message immediately
      const userMessage: ChatMessage = {
        id: generateId(),
        role: "user",
        content,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMessage]);

      // Create placeholder for assistant message
      const assistantId = generateId();
      currentMessageIdRef.current = assistantId;
      currentMessageRef.current = "";
      currentThinkingRef.current = "";
      currentToolExecutionsRef.current = [];

      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        timestamp: new Date(),
        toolExecutions: toolsEnabled ? [] : undefined,
      };
      setMessages((prev) => [...prev, assistantMessage]);

      // Build message history for context
      const messageHistory = messages.map((m) => ({
        role: m.role,
        content: m.content,
      }));
      messageHistory.push({ role: "user", content });

      const requestBody = {
        model,
        messages: messageHistory,
        temperature,
        session_id: sessionId,
        working_dir: workingDir,
        tools_enabled: toolsEnabled,
        project_id: "agent-hub",
      };

      const controller = new AbortController();
      abortControllerRef.current = controller;

      try {
        setStatus("streaming");

        const response = await fetch("/api/complete?stream=true", {
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

        while (true) {
          const { done, value } = await reader.read();

          if (done) {
            setStatus("idle");
            break;
          }

          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split("\n");

          for (const line of lines) {
            if (!line.trim() || !line.startsWith("data: ")) continue;

            const dataStr = line.slice(6); // Remove "data: " prefix
            if (dataStr === "[DONE]") {
              setStatus("idle");
              break;
            }

            try {
              const data = JSON.parse(dataStr);

              switch (data.type) {
                case "connected":
                  if (data.session_id) {
                    setCurrentSessionId(data.session_id);
                  }
                  break;

                case "thinking":
                  currentThinkingRef.current += data.content || "";
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === currentMessageIdRef.current
                        ? { ...m, thinking: currentThinkingRef.current }
                        : m,
                    ),
                  );
                  break;

                case "content":
                  currentMessageRef.current += data.content || "";
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === currentMessageIdRef.current
                        ? { ...m, content: currentMessageRef.current }
                        : m,
                    ),
                  );
                  break;

                case "done":
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === currentMessageIdRef.current
                        ? {
                            ...m,
                            content: currentMessageRef.current,
                            thinking: currentThinkingRef.current || undefined,
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
                  setStatus("idle");
                  break;

                case "cancelled":
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === currentMessageIdRef.current
                        ? {
                            ...m,
                            content: currentMessageRef.current,
                            thinking: currentThinkingRef.current || undefined,
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
                  setStatus("idle");
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
                    currentToolExecutionsRef.current = [
                      ...currentToolExecutionsRef.current,
                      newTool,
                    ];
                    setMessages((prev) =>
                      prev.map((m) =>
                        m.id === currentMessageIdRef.current
                          ? { ...m, toolExecutions: [...currentToolExecutionsRef.current] }
                          : m,
                      ),
                    );
                  }
                  break;

                case "tool_result":
                  if (data.tool_id) {
                    currentToolExecutionsRef.current = currentToolExecutionsRef.current.map(
                      (tool) =>
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
                        m.id === currentMessageIdRef.current
                          ? { ...m, toolExecutions: [...currentToolExecutionsRef.current] }
                          : m,
                      ),
                    );
                  }
                  break;

                case "error":
                  setError(data.error || "Unknown error");
                  setStatus("error");
                  break;
              }
            } catch (parseError) {
              console.warn("Failed to parse SSE data:", dataStr, parseError);
            }
          }
        }
      } catch (err: any) {
        if (err.name === "AbortError") {
          // Cancelled by user
          setStatus("idle");
        } else {
          setError(err.message || "Stream connection error");
          setStatus("error");
        }
      } finally {
        abortControllerRef.current = null;
      }
    },
    [messages, model, temperature, sessionId, status, workingDir, toolsEnabled],
  );

  const cancelStream = useCallback(() => {
    if (status !== "streaming" || !abortControllerRef.current) return;

    setStatus("cancelling");
    abortControllerRef.current.abort();
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
