"use client";

import { useCallback, useRef, useState } from "react";
import type {
  ChatMessage,
  StreamMessage,
  StreamRequest,
  StreamStatus,
} from "@/types/chat";

const WS_URL = "ws://localhost:8003/api/stream";
const DEFAULT_MODEL = "claude-sonnet-4-5-20250514";

interface UseChatStreamOptions {
  model?: string;
  sessionId?: string;
  maxTokens?: number;
  temperature?: number;
}

interface UseChatStreamReturn {
  messages: ChatMessage[];
  status: StreamStatus;
  error: string | null;
  sendMessage: (content: string) => void;
  cancelStream: () => void;
  clearMessages: () => void;
}

/**
 * Hook for managing chat streaming with WebSocket and cancellation support.
 */
export function useChatStream(
  options: UseChatStreamOptions = {}
): UseChatStreamReturn {
  const {
    model = DEFAULT_MODEL,
    sessionId,
    maxTokens = 4096,
    temperature = 1.0,
  } = options;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const currentMessageRef = useRef<string>("");
  const currentMessageIdRef = useRef<string>("");
  const statusRef = useRef<StreamStatus>(status);
  statusRef.current = status;

  const generateId = () =>
    `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

  const sendMessage = useCallback(
    (content: string) => {
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

      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMessage]);

      // Connect WebSocket
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus("streaming");

        // Build message history for context
        const messageHistory = messages.map((m) => ({
          role: m.role,
          content: m.content,
        }));
        messageHistory.push({ role: "user", content });

        const request: StreamRequest = {
          type: "request",
          model,
          messages: messageHistory,
          max_tokens: maxTokens,
          temperature,
          session_id: sessionId,
        };

        ws.send(JSON.stringify(request));
      };

      ws.onmessage = (event) => {
        const data: StreamMessage = JSON.parse(event.data);

        switch (data.type) {
          case "content":
            currentMessageRef.current += data.content || "";
            setMessages((prev) =>
              prev.map((m) =>
                m.id === currentMessageIdRef.current
                  ? { ...m, content: currentMessageRef.current }
                  : m
              )
            );
            break;

          case "done":
            setMessages((prev) =>
              prev.map((m) =>
                m.id === currentMessageIdRef.current
                  ? {
                      ...m,
                      content: currentMessageRef.current,
                      inputTokens: data.input_tokens,
                      outputTokens: data.output_tokens,
                    }
                  : m
              )
            );
            setStatus("idle");
            ws.close();
            break;

          case "cancelled":
            setMessages((prev) =>
              prev.map((m) =>
                m.id === currentMessageIdRef.current
                  ? {
                      ...m,
                      content: currentMessageRef.current,
                      cancelled: true,
                      inputTokens: data.input_tokens,
                      outputTokens: data.output_tokens,
                    }
                  : m
              )
            );
            setStatus("idle");
            ws.close();
            break;

          case "error":
            setError(data.error || "Unknown error");
            setStatus("error");
            ws.close();
            break;
        }
      };

      ws.onerror = () => {
        setError("WebSocket connection error");
        setStatus("error");
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (statusRef.current === "streaming" || statusRef.current === "cancelling") {
          setStatus("idle");
        }
      };
    },
    [messages, model, maxTokens, temperature, sessionId]
  );

  const cancelStream = useCallback(() => {
    if (status !== "streaming" || !wsRef.current) return;

    setStatus("cancelling");

    const cancelRequest: StreamRequest = {
      type: "cancel",
    };

    try {
      wsRef.current.send(JSON.stringify(cancelRequest));
    } catch {
      // WebSocket might already be closing
      setStatus("idle");
    }
  }, [status]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
    setStatus("idle");
  }, []);

  return {
    messages,
    status,
    error,
    sendMessage,
    cancelStream,
    clearMessages,
  };
}
