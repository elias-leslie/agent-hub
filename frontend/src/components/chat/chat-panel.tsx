"use client";

import { useMemo, useState, useRef, useCallback, useEffect } from "react";
import { useChatStream } from "@/hooks/use-chat-stream";
import { useTruncationToast } from "@/hooks/use-truncation-toast";
import { DegradedModeBanner } from "@/components/degraded-mode-banner";
import { MessageList } from "./message-list";
import { MessageInput } from "./message-input";
import { ActivityIndicator, type ActivityState } from "./activity-indicator";

/** Build voice WebSocket URL with required query params */
function buildVoiceWsUrl(): string {
  const protocol = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = typeof window !== "undefined" ? window.location.host : "localhost:8003";
  // Backend runs on port 8003, frontend on 3003 - need to adjust host for dev
  const backendHost = host.replace(":3003", ":8003");
  const userId = "user-" + Math.random().toString(36).substring(2, 9);
  return `${protocol}//${backendHost}/api/voice/ws?user_id=${userId}&app=agent-hub`;
}

/** Build TTS base URL */
function buildTtsBaseUrl(): string {
  const protocol = typeof window !== "undefined" ? window.location.protocol : "http:";
  const host = typeof window !== "undefined" ? window.location.host : "localhost:8003";
  // Backend runs on port 8003, frontend on 3003 - need to adjust host for dev
  const backendHost = host.replace(":3003", ":8003");
  return `${protocol}//${backendHost}`;
}

interface ChatPanelProps {
  model?: string;
  sessionId?: string;
  /** Working directory for tool execution (enables coding agent mode) */
  workingDir?: string;
  /** Enable tool calling for coding agent mode */
  toolsEnabled?: boolean;
}

/**
 * Main chat panel component with streaming and cancellation support.
 */
export function ChatPanel({
  model,
  sessionId,
  workingDir,
  toolsEnabled,
}: ChatPanelProps) {
  const {
    messages,
    status,
    error,
    sendMessage,
    cancelStream,
    clearMessages,
    editMessage,
    regenerateMessage,
  } = useChatStream({ model, sessionId, workingDir, toolsEnabled });

  // Show toast notifications when responses are truncated
  useTruncationToast(messages);

  // Build voice WebSocket URL (stable per session)
  const voiceWsUrl = useMemo(() => buildVoiceWsUrl(), []);
  const ttsBaseUrl = useMemo(() => buildTtsBaseUrl(), []);

  // Track if last message was sent via voice (to auto-speak response)
  const [wasVoiceMessage, setWasVoiceMessage] = useState(false);
  const speakTextRef = useRef<((text: string) => Promise<void>) | null>(null);
  const prevStatusRef = useRef(status);

  // When voice sends a message, mark it so we know to speak the response
  const handleVoiceSend = useCallback(() => {
    setWasVoiceMessage(true);
  }, []);

  // Store the speakText function when MessageInput provides it
  const handleSpeakTextReady = useCallback(
    (speakText: (text: string) => Promise<void>) => {
      speakTextRef.current = speakText;
    },
    []
  );

  // When streaming completes after a voice message, speak the response
  useEffect(() => {
    const wasStreaming =
      prevStatusRef.current === "streaming" ||
      prevStatusRef.current === "cancelling";
    const isNowIdle = status === "idle";

    if (wasStreaming && isNowIdle && wasVoiceMessage && speakTextRef.current) {
      // Find the last assistant message
      const lastAssistantMessage = [...messages]
        .reverse()
        .find((m) => m.role === "assistant");

      if (lastAssistantMessage?.content) {
        speakTextRef.current(lastAssistantMessage.content);
      }
      setWasVoiceMessage(false);
    }

    prevStatusRef.current = status;
  }, [status, wasVoiceMessage, messages]);

  const isStreaming = status === "streaming" || status === "cancelling";

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-700 px-4 py-3">
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
          Agent Hub
        </h1>
        <div className="flex items-center gap-3">
          {/* Activity indicator */}
          <ActivityIndicator state={status as ActivityState} />

          {/* Clear button */}
          {messages.length > 0 && !isStreaming && (
            <button
              onClick={clearMessages}
              className="text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Degraded mode banner */}
      <DegradedModeBanner />

      {/* Error banner */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border-b border-red-200 dark:border-red-800 px-4 py-2">
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        </div>
      )}

      {/* Messages */}
      <MessageList
        messages={messages}
        isStreaming={isStreaming}
        onEditMessage={editMessage}
        onRegenerateMessage={regenerateMessage}
      />

      {/* Input */}
      <MessageInput
        onSend={sendMessage}
        onCancel={cancelStream}
        status={status}
        voiceWsUrl={voiceWsUrl}
        ttsBaseUrl={ttsBaseUrl}
        onVoiceSend={handleVoiceSend}
        onSpeakTextReady={handleSpeakTextReady}
      />
    </div>
  );
}
