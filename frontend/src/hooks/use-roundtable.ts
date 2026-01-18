"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage } from "@/types/chat";

/**
 * Roundtable WebSocket message types
 */
export interface RoundtableWsMessage {
  type:
    | "connected"
    | "chunk"
    | "thinking"
    | "message_complete"
    | "volley_complete"
    | "error"
    | "closed";
  session_id?: string;
  agent?: "claude" | "gemini";
  content?: string;
  tokens?: number;
  message?: string;
  speaker_order?: string[];
  total_tokens?: number;
}

export interface RoundtableMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  agentType?: "claude" | "gemini";
  tokens?: number;
  timestamp: Date;
  isStreaming?: boolean;
}

export type RoundtableStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "streaming"
  | "error";

interface UseRoundtableOptions {
  /** Session ID to connect to */
  sessionId: string;
  /** Auto-connect on mount */
  autoConnect?: boolean;
  /** Base URL for API */
  baseUrl?: string;
}

interface UseRoundtableReturn {
  /** All messages in the session */
  messages: RoundtableMessage[];
  /** Connection status */
  status: RoundtableStatus;
  /** Error message if any */
  error: string | null;
  /** Last speaker order from volley */
  speakerOrder: string[];
  /** Whether a volley just completed (show Continue button) */
  volleyComplete: boolean;
  /** Connect to WebSocket */
  connect: () => void;
  /** Disconnect from WebSocket */
  disconnect: () => void;
  /** Send a message to the roundtable */
  sendMessage: (content: string, target?: "claude" | "gemini" | "both") => void;
  /** Continue the discussion (another round without new user input) */
  continueDiscussion: () => void;
  /** Clear messages */
  clearMessages: () => void;
}

/**
 * Get WebSocket URL based on current environment.
 * Defaults to backend port 8003 since frontend (3003) doesn't serve WebSockets.
 */
function getWsUrl(path: string, baseUrl?: string): string {
  if (typeof window === "undefined") {
    return `ws://localhost:8003${path}`;
  }
  if (baseUrl) {
    const url = new URL(baseUrl);
    const protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${url.host}${path}`;
  }
  // Default to backend on port 8003
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//localhost:8003${path}`;
}

/**
 * Hook for managing roundtable WebSocket connection and messages.
 *
 * @example
 * const {
 *   messages,
 *   status,
 *   sendMessage,
 *   continueDiscussion,
 *   volleyComplete
 * } = useRoundtable({ sessionId: "abc123" });
 *
 * // Send a message
 * sendMessage("What do you think about this?", "both");
 *
 * // Continue after volley completes
 * if (volleyComplete) {
 *   continueDiscussion();
 * }
 */
export function useRoundtable(
  options: UseRoundtableOptions
): UseRoundtableReturn {
  const { sessionId, autoConnect = true, baseUrl } = options;

  const [messages, setMessages] = useState<RoundtableMessage[]>([]);
  const [status, setStatus] = useState<RoundtableStatus>("disconnected");
  const [error, setError] = useState<string | null>(null);
  const [speakerOrder, setSpeakerOrder] = useState<string[]>([]);
  const [volleyComplete, setVolleyComplete] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const streamingMessageRef = useRef<Map<string, RoundtableMessage>>(new Map());

  /**
   * Create or update a streaming message for an agent.
   */
  const updateStreamingMessage = useCallback(
    (agent: "claude" | "gemini", content: string, append: boolean = true) => {
      setMessages((prev) => {
        // Find existing streaming message for this agent
        const existingIdx = prev.findIndex(
          (m) => m.agentType === agent && m.isStreaming
        );

        if (existingIdx >= 0) {
          // Update existing message
          const updated = [...prev];
          updated[existingIdx] = {
            ...updated[existingIdx],
            content: append
              ? updated[existingIdx].content + content
              : content,
          };
          return updated;
        }

        // Create new streaming message
        const newMessage: RoundtableMessage = {
          id: `${agent}-${Date.now()}`,
          role: "assistant",
          content,
          agentType: agent,
          timestamp: new Date(),
          isStreaming: true,
        };
        return [...prev, newMessage];
      });
    },
    []
  );

  /**
   * Finalize a streaming message.
   */
  const finalizeMessage = useCallback(
    (agent: "claude" | "gemini", tokens?: number) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.agentType === agent && m.isStreaming
            ? { ...m, isStreaming: false, tokens }
            : m
        )
      );
    },
    []
  );

  const connect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
    }

    setError(null);
    setStatus("connecting");

    const wsUrl = getWsUrl(
      `/api/orchestration/roundtable/${sessionId}/ws`,
      baseUrl
    );
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      // Wait for connected message
    };

    ws.onmessage = (event) => {
      try {
        const data: RoundtableWsMessage = JSON.parse(event.data);

        switch (data.type) {
          case "connected":
            setStatus("connected");
            break;

          case "chunk":
            if (data.agent && data.content) {
              setStatus("streaming");
              setVolleyComplete(false);
              updateStreamingMessage(data.agent, data.content, true);
            }
            break;

          case "thinking":
            // Could handle thinking content for display
            break;

          case "message_complete":
            if (data.agent) {
              finalizeMessage(data.agent, data.tokens);
            }
            break;

          case "volley_complete":
            setStatus("connected");
            setVolleyComplete(true);
            if (data.speaker_order) {
              setSpeakerOrder(data.speaker_order);
            }
            break;

          case "error":
            setError(data.message ?? "Unknown error");
            setStatus("error");
            break;

          case "closed":
            setStatus("disconnected");
            break;
        }
      } catch {
        console.error("Failed to parse roundtable message:", event.data);
      }
    };

    ws.onerror = () => {
      setError("WebSocket connection error");
      setStatus("error");
    };

    ws.onclose = () => {
      wsRef.current = null;
      setStatus("disconnected");
    };
  }, [sessionId, baseUrl, updateStreamingMessage, finalizeMessage]);

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      if (wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "close" }));
      }
      wsRef.current.close();
      wsRef.current = null;
    }
    setStatus("disconnected");
  }, []);

  const sendMessage = useCallback(
    (content: string, target: "claude" | "gemini" | "both" = "both") => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        setError("Not connected");
        return;
      }

      // Add user message to state
      const userMessage: RoundtableMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMessage]);
      setVolleyComplete(false);

      // Send to WebSocket
      wsRef.current.send(
        JSON.stringify({
          type: "message",
          content,
          target,
        })
      );
    },
    []
  );

  const continueDiscussion = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setError("Not connected");
      return;
    }

    setVolleyComplete(false);
    wsRef.current.send(JSON.stringify({ type: "continue" }));
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setVolleyComplete(false);
    setSpeakerOrder([]);
  }, []);

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect && sessionId) {
      connect();
    }

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [autoConnect, sessionId, connect]);

  return {
    messages,
    status,
    error,
    speakerOrder,
    volleyComplete,
    connect,
    disconnect,
    sendMessage,
    continueDiscussion,
    clearMessages,
  };
}
