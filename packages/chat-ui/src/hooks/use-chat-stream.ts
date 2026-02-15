"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage, StreamStatus } from "../types/chat";
import type { StreamState } from "./chat-stream/types";
import { loadSession } from "./chat-stream/session-loader";
import { sendMessage as sendMessageImpl } from "./chat-stream/send-message";

export interface ChatStreamApiConfig {
  fetchHeaders?: Record<string, string>;
  completeEndpoint?: string;
  sessionsEndpoint?: string;
  preferencesEndpoint?: string;
  fetchFn?: (url: string, options?: RequestInit) => Promise<Response>;
  projectId?: string;
  memoryGroupPrefix?: string;
}

interface UseChatStreamOptions {
  agentSlug?: string;
  sessionId?: string;
  temperature?: number;
  workingDir?: string;
  toolsEnabled?: boolean;
  apiConfig?: ChatStreamApiConfig;
}

interface UseChatStreamReturn {
  messages: ChatMessage[];
  status: StreamStatus;
  error: string | null;
  currentSessionId: string | null;
  sendMessage: (content: string, targetAgents?: string[]) => void;
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
    agentSlug = "chat",
    sessionId,
    temperature = 1.0,
    workingDir,
    toolsEnabled = false,
    apiConfig = {},
  } = options;

  const {
    fetchHeaders = {},
    completeEndpoint = "/api/complete",
    sessionsEndpoint = "/api/sessions",
    preferencesEndpoint = "/api/preferences",
    fetchFn = fetch,
    projectId = "agent-hub",
    memoryGroupPrefix = "agent:",
  } = apiConfig;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);

  const abortControllersRef = useRef<AbortController[]>([]);
  const streamStatesRef = useRef<Map<string, StreamState>>(new Map());

  // Load existing messages when sessionId is provided
  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      setCurrentSessionId(null);
      return;
    }

    const load = async () => {
      try {
        setStatus("connecting");
        const loadedMessages = await loadSession(sessionId, fetchFn, sessionsEndpoint);
        setCurrentSessionId(sessionId);
        setMessages(loadedMessages);
        setStatus("idle");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load session");
        setStatus("error");
      }
    };

    load();
  }, [sessionId]);

  const sendMessage = useCallback(
    async (content: string, targetAgents?: string[]) => {
      if (status !== "idle") return;

      await sendMessageImpl({
        content,
        targetAgents,
        agentSlug,
        messages,
        temperature,
        sessionId,
        workingDir,
        toolsEnabled,
        setMessages,
        setStatus,
        setError,
        setCurrentSessionId,
        streamStatesRef,
        abortControllersRef,
        fetchHeaders,
        completeEndpoint,
        preferencesEndpoint,
        projectId,
        memoryGroupPrefix,
      });
    },
    [messages, agentSlug, temperature, sessionId, status, workingDir, toolsEnabled, fetchHeaders, completeEndpoint, preferencesEndpoint, projectId, memoryGroupPrefix],
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
