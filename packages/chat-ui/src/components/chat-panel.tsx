"use client";

import { useMemo, useState, useRef, useCallback, useEffect } from "react";
import {
  Archive,
  CornerDownRight,
  PanelRight,
  PanelRightClose,
  Play,
  Split,
} from "lucide-react";
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
  onClear?: () => void;
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
  onClear,
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
    continueMessage,
    resumeSession,
    forkSession,
    compactMessages,
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
  const isBusy = status !== "idle" && status !== "error";
  const lastAssistantMessage = useMemo(
    () => [...messages].reverse().find((m) => m.role === "assistant") ?? null,
    [messages],
  );
  const runningTool = lastAssistantMessage?.toolExecutions?.find((tool) => tool.status === "running") ?? null;
  const tokenTotal = messages.reduce(
    (sum, message) => sum + (message.inputTokens ?? 0) + (message.outputTokens ?? 0) + (message.thinkingTokens ?? 0),
    0,
  );

  const handleContinueLatest = useCallback(() => {
    if (!lastAssistantMessage) return;
    continueMessage(lastAssistantMessage.id);
  }, [continueMessage, lastAssistantMessage]);

  const handleFork = useCallback(() => {
    void forkSession();
  }, [forkSession]);

  const handleCompact = useCallback(() => {
    compactMessages();
  }, [compactMessages]);

  const handleResume = useCallback(() => {
    const targetSessionId = sessionId ?? currentSessionId;
    if (!targetSessionId) return;
    void resumeSession(targetSessionId);
  }, [currentSessionId, resumeSession, sessionId]);

  return (
    <div className="flex flex-row h-full">
      <div className="flex flex-col flex-1 h-full min-w-0">
        {/* Header */}
        <div className="border-b border-gray-700 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <h1 className="truncate text-base font-semibold text-gray-100 sm:text-lg">
                {title}
              </h1>
              <div className="mt-1 hidden flex-wrap items-center gap-2 text-xs text-gray-500 md:flex">
                <span>{currentSessionId ? `session ${currentSessionId.slice(0, 8)}` : "new session"}</span>
                {agentSlug ? <span>agent {agentSlug}</span> : null}
                {workingDir ? <span className="truncate">cwd {workingDir}</span> : null}
                {toolsEnabled ? <span>tools on</span> : null}
                {tokenTotal > 0 ? <span>{tokenTotal.toLocaleString()} tokens</span> : null}
                {runningTool ? <span className="text-blue-300">running {runningTool.name}</span> : null}
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2">
            {/* Activity indicator */}
            <ActivityIndicator state={status as ActivityState} />

            <button
              onClick={handleContinueLatest}
              disabled={!lastAssistantMessage || isBusy}
              className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-800 hover:text-gray-200 disabled:cursor-not-allowed disabled:opacity-40"
              title="Continue response"
            >
              <CornerDownRight className="h-4 w-4" />
            </button>

            <button
              onClick={handleFork}
              disabled={!currentSessionId || isBusy}
              className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-800 hover:text-gray-200 disabled:cursor-not-allowed disabled:opacity-40"
              title="Fork session"
            >
              <Split className="h-4 w-4" />
            </button>

            <button
              onClick={handleCompact}
              disabled={messages.length < 8 || isBusy}
              className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-800 hover:text-gray-200 disabled:cursor-not-allowed disabled:opacity-40"
              title="Compact context"
            >
              <Archive className="h-4 w-4" />
            </button>

            {/* Clear button */}
            {messages.length > 0 && !isStreaming && (
              <button
                onClick={() => { clearMessages(); onClear?.(); }}
                className="text-sm text-gray-400 hover:text-gray-200"
              >
                Clear
              </button>
            )}

            {/* Debug Toggle */}
            {renderDebugPanel && (
              <button
                onClick={() => setShowDebug(!showDebug)}
                className="p-1.5 rounded-md text-gray-400 hover:bg-gray-800 transition-colors"
                title="Toggle Debug Panel"
              >
                {showDebug ? <PanelRightClose className="h-5 w-5" /> : <PanelRight className="h-5 w-5" />}
              </button>
            )}
            <button
              onClick={handleResume}
              disabled={!(sessionId ?? currentSessionId) || isBusy}
              className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-800 hover:text-gray-200 disabled:cursor-not-allowed disabled:opacity-40"
              title="Resume session"
            >
                <Play className="h-4 w-4" />
            </button>
            </div>
          </div>
        </div>

        {/* Optional banner slot */}
        {renderBanner?.()}

        {/* Error banner */}
        {error && (
          <div className="bg-red-900/20 border-b border-red-800 px-4 py-2">
            <p className="text-sm text-red-400">{error}</p>
          </div>
        )}

        {/* Messages */}
        <MessageList
          messages={messages}
          isStreaming={isStreaming}
          onEditMessage={editMessage}
          onRegenerateMessage={regenerateMessage}
          onContinueMessage={continueMessage}
          onContinueAs={(model, prompt) => sendMessage(prompt, [model])}
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
