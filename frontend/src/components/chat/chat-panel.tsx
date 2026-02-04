"use client";

import { useMemo, useState, useRef, useCallback, useEffect } from "react";
import { PanelRight, PanelRightClose } from "lucide-react";
import { useChatStream } from "@/hooks/use-chat-stream";
import { useTruncationToast } from "@/hooks/use-truncation-toast";
import { DegradedModeBanner } from "@/components/degraded-mode-banner";
import { MessageList } from "./message-list";
import { MessageInput } from "./message-input";
import { ActivityIndicator, type ActivityState } from "./activity-indicator";
import { DebugPanel, type DebugTrace } from "./debug-panel/debug-panel";
import type { Agent, AgentPreview } from "@/types/agent";
import { getWsUrl, getApiBaseUrl, fetchApi } from "@/lib/api-config";

/** Build voice WebSocket URL with required query params */
function buildVoiceWsUrl(): string {
  const userId = "user-" + Math.random().toString(36).substring(2, 9);
  return getWsUrl(`/api/voice/ws?user_id=${userId}&app=agent-hub`);
}

/** Build TTS base URL */
function buildTtsBaseUrl(): string {
  return getApiBaseUrl();
}

interface ChatPanelProps {
  agent?: Agent; // Full agent object if available
  agentSlug?: string; // Fallback if full agent not available
  sessionId?: string;
  /** Working directory for tool execution (enables coding agent mode) */
  workingDir?: string;
  /** Enable tool calling for coding agent mode */
  toolsEnabled?: boolean;
  /** Callback when a new session is created */
  onSessionCreated?: (sessionId: string) => void;
}

/**
 * Main chat panel component with streaming and cancellation support.
 */
export function ChatPanel({
  agent,
  agentSlug,
  sessionId,
  workingDir,
  toolsEnabled,
  onSessionCreated,
}: ChatPanelProps) {
  const {
    messages,
    status,
    error,
    currentSessionId,
    sendMessage,
    cancelStream,
    clearMessages,
    editMessage,
    regenerateMessage,
  } = useChatStream({ agentSlug: agent?.slug || agentSlug, sessionId, workingDir, toolsEnabled });

  // Debug Panel State
  const [showDebug, setShowDebug] = useState(false);
  const [agentPreview, setAgentPreview] = useState<AgentPreview | undefined>(undefined);

  // Fetch Agent Preview
  useEffect(() => {
    if (agent && showDebug) {
      fetchApi(`${getApiBaseUrl()}/api/agents/${agent.slug}/preview`)
        .then(res => res.ok ? res.json() : null)
        .then(data => setAgentPreview(data))
        .catch(err => console.error("Failed to fetch agent preview:", err));
    }
  }, [agent, showDebug]);

  // Derive Debug Trace
  const debugTrace: DebugTrace | null = useMemo(() => {
    const lastAssistantMessage = [...messages].reverse().find(m => m.role === "assistant");
    if (!lastAssistantMessage) return null;

    // Check if message has stats
    if (!lastAssistantMessage.inputTokens && !lastAssistantMessage.outputTokens) return null;

    return {
      model_used: lastAssistantMessage.agentModel || agent?.primary_model_id || "unknown",
      input_tokens: lastAssistantMessage.inputTokens || 0,
      output_tokens: lastAssistantMessage.outputTokens || 0,
      latency_ms: lastAssistantMessage.latency || 0,
      mandates_injected: agentPreview?.mandate_count || 0,
      mandate_uuids: agentPreview?.mandate_uuids || [],
      combined_prompt_length: agentPreview?.combined_prompt.length || 0,
    };
  }, [messages, agent, agentPreview]);

  // Notify parent when a new session is created
  useEffect(() => {
    if (currentSessionId && onSessionCreated) {
      onSessionCreated(currentSessionId);
    }
  }, [currentSessionId, onSessionCreated]);

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
    <div className="flex flex-row h-full">
      <div className="flex flex-col flex-1 h-full min-w-0">
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

            {/* Debug Toggle */}
            {agent && (
              <button
                onClick={() => setShowDebug(!showDebug)}
                className="p-1.5 rounded-md text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800 transition-colors"
                title="Toggle Debug Panel"
              >
                {showDebug ? <PanelRightClose className="h-5 w-5" /> : <PanelRight className="h-5 w-5" />}
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

      {/* Debug Panel Sidebar */}
      {showDebug && agent && (
        <DebugPanel
          agent={agent}
          preview={agentPreview}
          debugTrace={debugTrace}
          messages={messages}
        />
      )}
    </div>
  );
}
