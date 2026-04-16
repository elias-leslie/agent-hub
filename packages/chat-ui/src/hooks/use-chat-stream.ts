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
  loadInitialSession?: boolean;
}

interface UseChatStreamReturn {
  messages: ChatMessage[];
  status: StreamStatus;
  error: string | null;
  currentSessionId: string | null;
  sendMessage: (content: string, targetAgents?: string[], sessionIdOverride?: string) => void;
  cancelStream: () => void;
  clearMessages: () => void;
  resetSession: () => void;
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
    loadInitialSession = true,
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
  const [loadedSessionProjectId, setLoadedSessionProjectId] = useState<string | null>(null);
  const [sessionLoadEpoch, setSessionLoadEpoch] = useState(0);

  const abortControllersRef = useRef<AbortController[]>([]);
  const streamStatesRef = useRef<Map<string, StreamState>>(new Map());
  // Track session IDs established by the current stream to avoid reloading
  const streamEstablishedSessionRef = useRef<string | null>(null);
  // Track externally selected sessions that were already preloaded in sendMessage
  // so the session-loading effect does not immediately overwrite optimistic state.
  const preloadedSessionOverrideRef = useRef<string | null>(null);

  // Load existing messages when sessionId is provided externally
  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      setCurrentSessionId(null);
      setLoadedSessionProjectId(null);
      return;
    }

    if (!loadInitialSession) {
      setCurrentSessionId(sessionId);
      setLoadedSessionProjectId(null);
      return;
    }

    // Skip loading if this session was already preloaded for an explicit
    // session override send; we already have the correct baseline in state.
    if (preloadedSessionOverrideRef.current === sessionId) {
      preloadedSessionOverrideRef.current = null;
      return;
    }

    // Skip loading if this session was just created by our own stream —
    // we already have the messages in state and the backend may not have
    // persisted them yet (async save).
    if (streamEstablishedSessionRef.current === sessionId) {
      streamEstablishedSessionRef.current = null;
      return;
    }

    const load = async () => {
      try {
        setStatus("connecting");
        const loadedSession = await loadSession(sessionId, fetchFn, sessionsEndpoint);
        setCurrentSessionId(sessionId);
        setMessages(loadedSession.messages);
        setLoadedSessionProjectId(loadedSession.projectId);
        setStatus("idle");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load session");
        setStatus("error");
      }
    };

    load();
  }, [sessionId, loadInitialSession, sessionLoadEpoch]);

  // Wrap setCurrentSessionId to track stream-established sessions
  const setCurrentSessionIdWithTracking = useCallback(
    (id: React.SetStateAction<string | null>) => {
      if (typeof id === "string" && id) {
        streamEstablishedSessionRef.current = id;
      }
      setCurrentSessionId(id);
    },
    [],
  );

  const sendMessage = useCallback(
    async (content: string, targetAgents?: string[], sessionIdOverride?: string) => {
      // If a stream is active, interrupt it first (steering / user interruption)
      if (status !== "idle" && status !== "error") {
        // Abort frontend connections
        abortControllersRef.current.forEach((c) => c.abort());
        abortControllersRef.current = [];
        streamStatesRef.current.clear();

        // Request backend cancellation of tool execution (fire-and-forget)
        if (currentSessionId) {
          fetch(`${completeEndpoint}/cancel`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...fetchHeaders },
            body: JSON.stringify({ session_id: currentSessionId }),
          }).catch(() => {});
        }

        // Mark the last assistant message as cancelled
        setMessages((prev) => {
          let lastIdx = -1;
          for (let i = prev.length - 1; i >= 0; i--) {
            if (prev[i].role === "assistant") { lastIdx = i; break; }
          }
          if (lastIdx === -1) return prev;
          const updated = [...prev];
          updated[lastIdx] = { ...updated[lastIdx], cancelled: true };
          return updated;
        });
      }

      let effectiveMessages = messages;
      let effectiveProjectId = loadedSessionProjectId ?? projectId;
      let effectiveSessionId = sessionIdOverride ?? currentSessionId ?? sessionId;
      const requestedSessionId = sessionIdOverride ?? sessionId;

      if (requestedSessionId && requestedSessionId !== currentSessionId) {
        try {
          preloadedSessionOverrideRef.current = requestedSessionId;
          const loadedSession = await loadSession(requestedSessionId, fetchFn, sessionsEndpoint);
          effectiveMessages = loadedSession.messages;
          effectiveProjectId = loadedSession.projectId ?? projectId;
          effectiveSessionId = requestedSessionId;
          setCurrentSessionId(requestedSessionId);
          setLoadedSessionProjectId(loadedSession.projectId);
          setMessages(loadedSession.messages);
        } catch (err) {
          preloadedSessionOverrideRef.current = null;
          setError(err instanceof Error ? err.message : "Failed to load session");
          setStatus("error");
          if (requestedSessionId === sessionIdOverride) {
            setSessionLoadEpoch((value) => value + 1);
          }
          return;
        }
      }

      await sendMessageImpl({
        content,
        targetAgents,
        agentSlug,
        messages: effectiveMessages,
        temperature,
        sessionId: effectiveSessionId,
        workingDir,
        toolsEnabled,
        setMessages,
        setStatus,
        setError,
        setCurrentSessionId: setCurrentSessionIdWithTracking,
        streamStatesRef,
        abortControllersRef,
        fetchHeaders,
        completeEndpoint,
        preferencesEndpoint,
        projectId: effectiveProjectId,
        memoryGroupPrefix,
      });
    },
    [messages, agentSlug, temperature, sessionId, currentSessionId, status, workingDir, toolsEnabled, fetchHeaders, completeEndpoint, preferencesEndpoint, projectId, loadedSessionProjectId, memoryGroupPrefix, setCurrentSessionIdWithTracking, fetchFn, sessionsEndpoint, loadInitialSession],
  );

  const cancelStream = useCallback(() => {
    if ((status !== "streaming" && status !== "reconnecting") || abortControllersRef.current.length === 0) return;
    setStatus("cancelling");
    abortControllersRef.current.forEach((controller) => controller.abort());
  }, [status]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
    setStatus("idle");
  }, []);

  const resetSession = useCallback(() => {
    abortControllersRef.current.forEach((controller) => controller.abort());
    abortControllersRef.current = [];
    streamStatesRef.current.clear();
    streamEstablishedSessionRef.current = null;
    preloadedSessionOverrideRef.current = null;
    setCurrentSessionId(null);
    setLoadedSessionProjectId(null);
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
    resetSession,
    editMessage,
    regenerateMessage,
  };
}
