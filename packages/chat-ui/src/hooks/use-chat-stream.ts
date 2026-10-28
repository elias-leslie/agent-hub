"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRequiredChatClient, type ChatHubClient } from "../client";
import type { ChatMessage, StreamStatus } from "../types/chat";
import type { CompletionRequest, StreamState } from "./chat-stream/types";
import { loadSession, type LoadedSession } from "./chat-stream/session-loader";
import { sendMessage as sendMessageImpl } from "./chat-stream/send-message";
import { attachToTurn } from "./chat-stream/stream-processor";
import { generateId } from "./chat-stream/utils";

/** What the host knows about the conversation. Where Agent Hub is lives in the client, not here. */
export interface ChatStreamConfig {
  projectId?: string;
  memoryGroupPrefix?: string;
  externalId?: string;
  parentSessionId?: string;
  sourceMetadata?: CompletionRequest["source_metadata"];
  workContext?: CompletionRequest["work_context"];
  includeRoles?: string[];
  promptMode?: CompletionRequest["prompt_mode"];
  useMemory?: boolean;
  thinkingLevel?: string | null;
  currentBranch?: string | null;
  /** Catalog model to ask for instead of the agent's own routing. Empty or omitted: canonical routing. */
  model?: string | null;
}

/** How long a new message waits for the turn it interrupts to wind down before it is sent anyway. */
const INTERRUPT_WAIT_MS = 20_000;

interface UseChatStreamOptions {
  /** The Agent Hub client; falls back to the one from a `ChatClientProvider`. */
  client?: ChatHubClient | null;
  agentSlug: string;
  sessionId?: string;
  temperature?: number;
  workingDir?: string;
  toolsEnabled?: boolean;
  config?: ChatStreamConfig;
  /** Load the session's messages when `sessionId` is given, and rejoin its turn if one is running. Default true. */
  loadInitialSession?: boolean;
}

interface UseChatStreamReturn {
  messages: ChatMessage[];
  status: StreamStatus;
  error: string | null;
  currentSessionId: string | null;
  /** Where the running turn is (`waiting_for_model`, `thinking`, `responding`, `running_tool:name`, `retrying`), else null. */
  turnPhase: string | null;
  sendMessage: (content: string, targetAgents?: string[], sessionIdOverride?: string) => void;
  cancelStream: () => void;
  clearMessages: () => void;
  resetSession: () => void;
  resumeSession: (sessionId: string) => Promise<boolean>;
  forkSession: (forkAtTurn?: number | null) => Promise<string | null>;
  compactMessages: (keepRecent?: number) => boolean;
  editMessage: (messageId: string, newContent: string) => void;
  regenerateMessage: (messageId: string) => void;
  continueMessage: (messageId: string) => void;
}

/**
 * Hook for managing chat streaming through an Agent Hub client. The server owns each turn: a session opened while a
 * turn is running rejoins it (replaying what it already said), so a reloaded page keeps streaming.
 */
export function useChatStream(
  options: UseChatStreamOptions,
): UseChatStreamReturn {
  const {
    agentSlug,
    sessionId,
    temperature = 1.0,
    workingDir,
    toolsEnabled = false,
    config = {},
    loadInitialSession = true,
  } = options;

  const client = useRequiredChatClient(options.client);
  // Effects and callbacks read the latest client without re-running when a host rebuilds it.
  const clientRef = useRef(client);
  clientRef.current = client;

  const {
    projectId = "agent-hub",
    memoryGroupPrefix = "agent:",
    externalId,
    parentSessionId,
    sourceMetadata,
    workContext,
    includeRoles,
    promptMode,
    useMemory,
    thinkingLevel,
    currentBranch,
    model,
  } = config;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [loadedSessionProjectId, setLoadedSessionProjectId] = useState<string | null>(null);
  const [sessionLoadEpoch, setSessionLoadEpoch] = useState(0);
  const [turnPhase, setTurnPhase] = useState<string | null>(null);

  const abortControllersRef = useRef<AbortController[]>([]);
  // The run that owns the controllers above: a send, or a rejoined turn.
  const activeRunRef = useRef<Promise<unknown> | null>(null);
  const streamStatesRef = useRef<Map<string, StreamState>>(new Map());
  // Track session IDs established by the current stream to avoid reloading
  const streamEstablishedSessionRef = useRef<string | null>(null);
  // Track externally selected sessions that were already preloaded in sendMessage
  // so the session-loading effect does not immediately overwrite optimistic state.
  const preloadedSessionOverrideRef = useRef<string | null>(null);

  // Rejoin a turn that is running on the server: show what it has said so far and follow it to its end.
  const followRunningTurn = useCallback(
    async (
      targetSessionId: string,
      loaded: LoadedSession,
      controller: AbortController,
      isStale: () => boolean,
    ) => {
      const mine = [controller];
      abortControllersRef.current = mine;
      const assistantId = generateId();
      const state: StreamState = { content: "", thinking: "", tools: [], lastSeq: 0 };
      streamStatesRef.current.set(assistantId, state);

      setCurrentSessionId(targetSessionId);
      setLoadedSessionProjectId(loaded.projectId);
      setMessages([
        ...loaded.messages,
        { id: assistantId, role: "assistant", content: "", timestamp: new Date(), agentModel: agentSlug, toolExecutions: [] },
      ]);
      setError(null);
      setStatus("streaming");
      setTurnPhase(loaded.turnPhase ?? "waiting_for_model");

      const run = (async () => {
        try {
          const outcome = await attachToTurn(
            clientRef.current,
            targetSessionId,
            { assistantId, streamState: state, setMessages, setCurrentSessionId, setStatus, setTurnPhase },
            controller.signal,
          );
          if (isStale() || abortControllersRef.current !== mine) return;
          if (outcome === "idle") {
            // It ended between the read and the attach: the stored session has the result.
            const fresh = await loadSession(clientRef.current, targetSessionId);
            if (isStale() || abortControllersRef.current !== mine) return;
            setMessages(fresh.messages);
            setLoadedSessionProjectId(fresh.projectId);
          }
          setStatus("idle");
        } catch (err) {
          if (isStale() || abortControllersRef.current !== mine) return;
          if (err instanceof Error && err.name === "AbortError") {
            setStatus("idle");
            return;
          }
          setError(err instanceof Error ? err.message : "Stream connection error");
          setStatus("error");
        } finally {
          if (abortControllersRef.current === mine) {
            abortControllersRef.current = [];
            streamStatesRef.current.clear();
          }
        }
      })();
      activeRunRef.current = run;
      await run;
    },
    [agentSlug],
  );

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

    // Ignore a slower load for a session the user already switched away from.
    let cancelled = false;
    const controller = new AbortController();
    const load = async () => {
      try {
        setStatus("connecting");
        const loadedSession = await loadSession(clientRef.current, sessionId);
        if (cancelled) return;
        if (loadedSession.turnState === "running") {
          await followRunningTurn(sessionId, loadedSession, controller, () => cancelled);
          return;
        }
        setCurrentSessionId(sessionId);
        setMessages(loadedSession.messages);
        setLoadedSessionProjectId(loadedSession.projectId);
        setStatus("idle");
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load session");
        setStatus("error");
      }
    };

    load();
    return () => {
      cancelled = true;
      // Only drops this connection: the turn keeps running on the server.
      controller.abort();
    };
  }, [sessionId, loadInitialSession, sessionLoadEpoch, followRunningTurn]);

  // Leaving the page drops the connections; running turns carry on server-side.
  useEffect(() => {
    return () => {
      abortControllersRef.current.forEach((controller) => controller.abort());
    };
  }, []);

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
    async (
      content: string,
      targetAgents?: string[],
      sessionIdOverride?: string,
      historyOverride?: ChatMessage[],
    ) => {
      // If a turn is active, interrupt it first (steering / user interruption). The server runs one turn per
      // session, so the running one is cancelled and given a moment to end before the new one is sent.
      if (status !== "idle" && status !== "error") {
        const previousRun = activeRunRef.current;
        const interruptedSessionId = currentSessionId ?? sessionId;
        // Only a connected turn needs stopping; a session that is still loading has none.
        if (interruptedSessionId && abortControllersRef.current.length > 0) {
          setStatus("cancelling");
          await clientRef.current.turns.cancel(interruptedSessionId).catch(() => undefined);
          if (previousRun) {
            let timer: ReturnType<typeof setTimeout> | undefined;
            await Promise.race([
              previousRun.catch(() => undefined),
              new Promise<void>((resolve) => {
                timer = setTimeout(resolve, INTERRUPT_WAIT_MS);
              }),
            ]);
            clearTimeout(timer);
          }
        }

        // Drop whatever connections are left
        abortControllersRef.current.forEach((c) => c.abort());
        abortControllersRef.current = [];
        streamStatesRef.current.clear();

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

      let effectiveMessages = historyOverride ?? messages;
      let effectiveProjectId = loadedSessionProjectId ?? projectId;
      let effectiveSessionId = sessionIdOverride ?? currentSessionId ?? sessionId;
      const requestedSessionId = sessionIdOverride ?? sessionId;

      if (requestedSessionId && requestedSessionId !== currentSessionId) {
        try {
          preloadedSessionOverrideRef.current = requestedSessionId;
          const loadedSession = await loadSession(clientRef.current, requestedSessionId);
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

      const run = sendMessageImpl({
        client: clientRef.current,
        content,
        targetAgents,
        agentSlug,
        includeRoles,
        promptMode,
        useMemory,
        messages: effectiveMessages,
        temperature,
        sessionId: effectiveSessionId,
        workingDir,
        toolsEnabled,
        setMessages,
        setStatus,
        setError,
        setCurrentSessionId: setCurrentSessionIdWithTracking,
        setTurnPhase,
        streamStatesRef,
        abortControllersRef,
        projectId: effectiveProjectId,
        memoryGroupPrefix,
        externalId,
        parentSessionId,
        sourceMetadata,
        workContext,
        thinkingLevel,
        currentBranch,
        model,
      });
      activeRunRef.current = run;
      await run;
    },
    [messages, agentSlug, temperature, sessionId, currentSessionId, status, workingDir, toolsEnabled, projectId, loadedSessionProjectId, memoryGroupPrefix, externalId, parentSessionId, sourceMetadata, workContext, includeRoles, promptMode, useMemory, thinkingLevel, currentBranch, model, setCurrentSessionIdWithTracking, loadInitialSession],
  );

  const cancelStream = useCallback(() => {
    if ((status !== "streaming" && status !== "reconnecting") || abortControllersRef.current.length === 0) return;
    setStatus("cancelling");
    const target = currentSessionId ?? sessionId;
    const dropConnections = () => abortControllersRef.current.forEach((controller) => controller.abort());
    // Before the session is known the turn cannot be named; the connection is all there is to drop.
    if (!target) {
      dropConnections();
      return;
    }
    // The server stops the turn after the tool it is running; the stream then ends with cancel_acknowledged.
    clientRef.current.turns.cancel(target).then(
      (result) => {
        // Nothing was running on the server: nothing will end the stream for us.
        if (!result.cancelled) dropConnections();
      },
      (err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to cancel the turn");
        setStatus("streaming");
      },
    );
  }, [status, currentSessionId, sessionId]);

  const currentSessionIdRef = useRef<string | null>(null);
  currentSessionIdRef.current = currentSessionId;

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
    setStatus("idle");
  }, []);

  const resetSession = useCallback(() => {
    // Starting over also stops the turn, as dropping the connection used to.
    const running = abortControllersRef.current.length > 0 ? currentSessionIdRef.current : null;
    if (running) void clientRef.current.turns.cancel(running).catch(() => undefined);
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
    setTurnPhase(null);
  }, []);

  const resumeSession = useCallback(
    async (targetSessionId: string) => {
      try {
        setStatus("connecting");
        abortControllersRef.current.forEach((controller) => controller.abort());
        const loadedSession = await loadSession(clientRef.current, targetSessionId);
        if (loadedSession.turnState === "running") {
          void followRunningTurn(targetSessionId, loadedSession, new AbortController(), () => false);
          return true;
        }
        setCurrentSessionId(targetSessionId);
        setLoadedSessionProjectId(loadedSession.projectId);
        setMessages(loadedSession.messages);
        setError(null);
        setStatus("idle");
        return true;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to resume session");
        setStatus("error");
        return false;
      }
    },
    [followRunningTurn],
  );

  const forkSession = useCallback(
    async (forkAtTurn?: number | null) => {
      const sourceSessionId = currentSessionId ?? sessionId;
      if (!sourceSessionId || status !== "idle") return null;

      try {
        setStatus("connecting");
        const fork = await clientRef.current.sessions.fork(sourceSessionId, { fork_at_turn: forkAtTurn ?? null });
        const resumed = await resumeSession(fork.id);
        return resumed ? fork.id : null;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fork session");
        setStatus("error");
        return null;
      }
    },
    [currentSessionId, sessionId, status, resumeSession],
  );

  const compactMessages = useCallback((keepRecent = 6) => {
    if (status !== "idle" || messages.length <= keepRecent + 1) return false;

    const compacted = messages.slice(0, -keepRecent);
    const kept = messages.slice(-keepRecent);
    const summaryLines = compacted
      .slice(-10)
      .map((message) => {
        const text = message.content.replace(/\s+/g, " ").trim();
        const excerpt = text.length > 180 ? `${text.slice(0, 177)}...` : text;
        return `- ${message.role}: ${excerpt || "[empty]"}`;
      })
      .join("\n");

    const summaryMessage: ChatMessage = {
      id: generateId(),
      role: "system",
      content: [
        `[Context Summary: ${compacted.length} earlier messages compacted]`,
        summaryLines,
      ].filter(Boolean).join("\n\n"),
      timestamp: new Date(),
      compacted: true,
      statusLabel: "Compacted context",
      contextHints: [
        { label: "Kept", value: `${kept.length} recent` },
        { label: "Compacted", value: `${compacted.length}` },
      ],
    };

    setMessages([summaryMessage, ...kept]);
    setError(null);
    return true;
  }, [messages, status]);

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

      // Drop the original user turn too: sendMessage re-adds it, and the
      // regenerated answer must not see the reply it replaces as history.
      const userMessage = messages[userMessageIndex];
      const history = messages.slice(0, userMessageIndex);
      setMessages(history);
      void sendMessage(userMessage.content, undefined, undefined, history);
    },
    [messages, status, sendMessage],
  );

  const continueMessage = useCallback(
    (messageId: string) => {
      if (status !== "idle") return;
      const message = messages.find((m) => m.id === messageId);
      if (!message || message.role !== "assistant") return;
      sendMessage("Continue from your previous response.");
    },
    [messages, status, sendMessage],
  );

  return {
    messages,
    status,
    error,
    currentSessionId,
    turnPhase,
    sendMessage,
    cancelStream,
    clearMessages,
    resetSession,
    resumeSession,
    forkSession,
    compactMessages,
    editMessage,
    regenerateMessage,
    continueMessage,
  };
}
