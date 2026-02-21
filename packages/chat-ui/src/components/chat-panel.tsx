"use client";

import { useMemo, useState, useRef, useCallback, useEffect } from "react";
import { PanelRight, PanelRightClose } from "lucide-react";
import { useChatStream, type ChatStreamApiConfig } from "../hooks/use-chat-stream";
import type { ChatMessage } from "../types/chat";
import { MessageList } from "./message-list";
import { MessageInput } from "./message-input";
import { ActivityIndicator, type ActivityState } from "./activity-indicator";

interface ChatPanelProps {
  agentSlug?: string;
  sessionId?: string;
  workingDir?: string;
  toolsEnabled?: boolean;
  onSessionCreated?: (sessionId: string) => void;
  initialPrompt?: string;
  title?: string;
  apiConfig?: ChatStreamApiConfig;
  fetchFn?: (url: string, options?: RequestInit) => Promise<Response>;
  modelsEndpoint?: string;
  voiceWsUrl?: string;
  ttsBaseUrl?: string;
  /** When true, speak every assistant response (not just after voice input) */
  alwaysSpeak?: boolean;
  renderBanner?: () => React.ReactNode;
  renderDebugPanel?: (props: { messages: ChatMessage[] }) => React.ReactNode;
  onMessagesChange?: (messages: ChatMessage[]) => void;
}

export function ChatPanel({
  agentSlug,
  sessionId,
  workingDir,
  toolsEnabled,
  onSessionCreated,
  initialPrompt,
  title = "Agent Hub",
  apiConfig,
  fetchFn,
  modelsEndpoint,
  voiceWsUrl: voiceWsUrlProp,
  ttsBaseUrl: ttsBaseUrlProp,
  alwaysSpeak = false,
  renderBanner,
  renderDebugPanel,
  onMessagesChange,
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
  } = useChatStream({ agentSlug, sessionId, workingDir, toolsEnabled, apiConfig });

  const [showDebug, setShowDebug] = useState(false);

  // Notify parent when a new session is created
  useEffect(() => {
    if (currentSessionId && onSessionCreated) {
      onSessionCreated(currentSessionId);
    }
  }, [currentSessionId, onSessionCreated]);

  // Notify parent when messages change
  useEffect(() => {
    if (onMessagesChange) {
      onMessagesChange(messages);
    }
  }, [messages, onMessagesChange]);

  // Track if last message was sent via voice (to auto-speak response)
  const [wasVoiceMessage, setWasVoiceMessage] = useState(false);
  const speakTextRef = useRef<((text: string, voice?: string) => Promise<void>) | null>(null);
  const prevStatusRef = useRef(status);

  // Voice preferences lifted from SpeakerButton
  const [selectedVoice, setSelectedVoice] = useState<string>("en-US-AriaNeural");
  const [dbTtsEnabled, setDbTtsEnabled] = useState(false);

  // When voice sends a message, mark it so we know to speak the response
  const handleVoiceSend = useCallback(() => {
    setWasVoiceMessage(true);
  }, []);

  // Store the speakText function when MessageInput provides it
  const handleSpeakTextReady = useCallback(
    (speakText: (text: string, voice?: string) => Promise<void>) => {
      speakTextRef.current = speakText;
    },
    []
  );

  const handleVoiceChange = useCallback((voiceId: string) => {
    setSelectedVoice(voiceId);
  }, []);

  const handleEnabledChange = useCallback((enabled: boolean) => {
    setDbTtsEnabled(enabled);
  }, []);

  // When streaming completes, speak the response (DB preference or alwaysSpeak fallback)
  useEffect(() => {
    const wasStreaming =
      prevStatusRef.current === "streaming" ||
      prevStatusRef.current === "reconnecting" ||
      prevStatusRef.current === "cancelling";
    const isNowIdle = status === "idle";

    const shouldSpeak = dbTtsEnabled || alwaysSpeak;

    if (wasStreaming && isNowIdle && shouldSpeak && speakTextRef.current) {
      // Find the last assistant message
      const lastAssistantMessage = [...messages]
        .reverse()
        .find((m) => m.role === "assistant");

      if (lastAssistantMessage?.content) {
        speakTextRef.current(lastAssistantMessage.content, selectedVoice);
      }
      setWasVoiceMessage(false);
    }

    prevStatusRef.current = status;
  }, [status, wasVoiceMessage, alwaysSpeak, dbTtsEnabled, selectedVoice, messages]);

  const isStreaming = status === "streaming" || status === "reconnecting" || status === "cancelling";

  return (
    <div className="flex flex-row h-full">
      <div className="flex flex-col flex-1 h-full min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-700 px-4 py-3">
          <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            {title}
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
            {renderDebugPanel && (
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

        {/* Optional banner slot */}
        {renderBanner?.()}

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
          voiceWsUrl={voiceWsUrlProp}
          ttsBaseUrl={ttsBaseUrlProp}
          preferencesEndpoint={apiConfig?.preferencesEndpoint}
          onVoiceSend={handleVoiceSend}
          onSpeakTextReady={handleSpeakTextReady}
          onVoiceChange={handleVoiceChange}
          onEnabledChange={handleEnabledChange}
          initialPrompt={initialPrompt}
          fetchFn={fetchFn}
          modelsEndpoint={modelsEndpoint}
        />
      </div>

      {/* Debug Panel Sidebar */}
      {showDebug && renderDebugPanel && renderDebugPanel({ messages })}
    </div>
  );
}
