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
import { ChatClientProvider, useRequiredChatClient, type ChatHubClient } from "../client";
import { useChatStream, type ChatStreamConfig } from "../hooks/use-chat-stream";
import { describePhase } from "../hooks/chat-stream/turn-phase";
import type { ChatMessage } from "../types/chat";
import type { ChatVoice } from "../types/voice";
import { MessageList } from "./message-list";
import { MessageInput } from "./message-input";
import { ActivityIndicator, type ActivityState } from "./activity-indicator";

interface ChatPanelProps {
  agentSlug: string;
  sessionId?: string;
  workingDir?: string;
  toolsEnabled?: boolean;
  onSessionCreated?: (sessionId: string) => void;
  onClear?: () => void;
  initialPrompt?: string;
  autoSendPrompt?: string | null;
  autoSendKey?: string | number | null;
  title?: string;
  /** The Agent Hub client (`createClient` from `@agent-hub/sdk`); falls back to a `ChatClientProvider` above the panel. */
  client?: ChatHubClient | null;
  config?: ChatStreamConfig;
  /** Voice input and output from `useChatVoice` (`@agent-hub/chat-ui/voice`). Omit for a chat without voice. */
  voice?: ChatVoice;
  /** When true, speak every assistant response (not just after voice input) */
  alwaysSpeak?: boolean;
  renderBanner?: () => React.ReactNode;
  renderDebugPanel?: (props: { messages: ChatMessage[] }) => React.ReactNode;
  onMessagesChange?: (messages: ChatMessage[]) => void;
}

export function ChatPanel({ client: clientProp, ...props }: ChatPanelProps) {
  const client = useRequiredChatClient(clientProp);
  return (
    <ChatClientProvider client={client}>
      <ChatPanelBody {...props} />
    </ChatClientProvider>
  );
}

function ChatPanelBody({
  agentSlug,
  sessionId,
  workingDir,
  toolsEnabled,
  onSessionCreated,
  onClear,
  initialPrompt,
  autoSendPrompt,
  autoSendKey,
  title = "Agent Hub",
  config,
  voice,
  alwaysSpeak = false,
  renderBanner,
  renderDebugPanel,
  onMessagesChange,
}: Omit<ChatPanelProps, "client">) {
  const {
    messages,
    status,
    error,
    currentSessionId,
    turnPhase,
    sendMessage,
    cancelStream,
    clearMessages,
    editMessage,
    regenerateMessage,
    continueMessage,
    resumeSession,
    forkSession,
    compactMessages,
  } = useChatStream({ agentSlug, sessionId, workingDir, toolsEnabled, config });

  const [showDebug, setShowDebug] = useState(false);
  const lastNotifiedSessionId = useRef<string | null>(null);

  // Notify parent when a new session is created
  useEffect(() => {
    if (currentSessionId && onSessionCreated) {
      if (lastNotifiedSessionId.current === currentSessionId) {
        return;
      }
      lastNotifiedSessionId.current = currentSessionId;
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
  const prevStatusRef = useRef(status);

  // When voice sends a message, mark it so we know to speak the response
  const handleVoiceSend = useCallback(() => {
    setWasVoiceMessage(true);
  }, []);

  // When streaming completes, speak the response (the voice preference or alwaysSpeak)
  useEffect(() => {
    const wasStreaming =
      prevStatusRef.current === "streaming" ||
      prevStatusRef.current === "reconnecting" ||
      prevStatusRef.current === "cancelling";
    const isNowIdle = status === "idle";

    const shouldSpeak = Boolean(voice) && (voice?.ttsEnabled || alwaysSpeak);

    if (wasStreaming && isNowIdle && shouldSpeak && voice) {
      // Find the last assistant message
      const lastAssistantMessage = [...messages]
        .reverse()
        .find((m) => m.role === "assistant");

      if (lastAssistantMessage?.content) {
        void voice.speakText(lastAssistantMessage.content, voice.selectedVoice);
      }
      setWasVoiceMessage(false);
    }

    prevStatusRef.current = status;
  }, [status, wasVoiceMessage, alwaysSpeak, voice, messages]);

  const isStreaming = status === "streaming" || status === "reconnecting" || status === "cancelling";
  const isBusy = status !== "idle" && status !== "error";
  const lastAutoSendKey = useRef<string | number | null>(null);
  const lastAssistantMessage = useMemo(
    () => [...messages].reverse().find((m) => m.role === "assistant") ?? null,
    [messages],
  );
  const runningTool = lastAssistantMessage?.toolExecutions?.find((tool) => tool.status === "running") ?? null;
  const tokenTotal = messages.reduce(
    (sum, message) => sum + (message.inputTokens ?? 0) + (message.outputTokens ?? 0) + (message.thinkingTokens ?? 0),
    0,
  );

  const phaseLabel = isBusy ? describePhase(turnPhase) : null;
  // The pill names the turn's phase while it streams: thinking, calling a tool, or responding.
  const phaseName = (isBusy && status === "streaming" ? turnPhase ?? "" : "").split(":", 1)[0];
  const pillState: ActivityState =
    phaseName === "thinking"
      ? "thinking"
      : phaseName === "running_tool"
        ? "calling_tool"
        : (status as ActivityState);

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

  useEffect(() => {
    if (!autoSendPrompt || autoSendKey === null || autoSendKey === undefined || isBusy) {
      return;
    }
    if (lastAutoSendKey.current === autoSendKey) {
      return;
    }
    lastAutoSendKey.current = autoSendKey;
    sendMessage(autoSendPrompt);
  }, [autoSendKey, autoSendPrompt, isBusy, sendMessage]);

  return (
    <div className="flex flex-row h-full">
      <div className="flex flex-col flex-1 h-full min-w-0">
        {/* Header */}
        <div className="border-b border-border bg-card/35 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <h1 className="truncate text-base font-semibold text-foreground sm:text-lg">
                {title}
              </h1>
              <div className="mt-1 hidden flex-wrap items-center gap-2 text-xs text-muted-foreground md:flex">
                <span>{currentSessionId ? `session ${currentSessionId.slice(0, 8)}` : "new session"}</span>
                <span>agent {agentSlug}</span>
                {workingDir ? <span className="truncate">cwd {workingDir}</span> : null}
                {toolsEnabled ? <span>tools on</span> : null}
                {tokenTotal > 0 ? <span>{tokenTotal.toLocaleString()} tokens</span> : null}
                {runningTool ? <span className="text-primary">running {runningTool.name}</span> : null}
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2">
            {/* Activity indicator */}
            <ActivityIndicator state={pillState} />
            {phaseLabel ? (
              <span data-testid="turn-phase" className="sr-only" aria-live="polite">
                {phaseLabel}
              </span>
            ) : null}

            <button
              onClick={handleContinueLatest}
              disabled={!lastAssistantMessage || isBusy}
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-40"
              title="Continue response"
            >
              <CornerDownRight className="h-4 w-4" />
            </button>

            <button
              onClick={handleFork}
              disabled={!currentSessionId || isBusy}
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-40"
              title="Fork session"
            >
              <Split className="h-4 w-4" />
            </button>

            <button
              onClick={handleCompact}
              disabled={messages.length < 8 || isBusy}
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-40"
              title="Compact context"
            >
              <Archive className="h-4 w-4" />
            </button>

            {/* Clear button */}
            {messages.length > 0 && !isStreaming && (
              <button
                onClick={() => { clearMessages(); onClear?.(); }}
                className="text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                Clear
              </button>
            )}

            {/* Debug Toggle */}
            {renderDebugPanel && (
              <button
                onClick={() => setShowDebug(!showDebug)}
                className="p-1.5 rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                title="Toggle Debug Panel"
              >
                {showDebug ? <PanelRightClose className="h-5 w-5" /> : <PanelRight className="h-5 w-5" />}
              </button>
            )}
            <button
              onClick={handleResume}
              disabled={!(sessionId ?? currentSessionId) || isBusy}
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-40"
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
          <div role="alert" className="border-b border-destructive/30 bg-destructive/10 px-4 py-2">
            <p className="text-sm text-destructive">{error}</p>
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
          emptyLabel={error ? "No messages loaded" : undefined}
        />

        {/* Input */}
        <MessageInput
          agentSlug={agentSlug}
          onSend={sendMessage}
          onCancel={cancelStream}
          status={status}
          voice={voice}
          onVoiceSend={handleVoiceSend}
          initialPrompt={initialPrompt}
        />
      </div>

      {/* Debug Panel Sidebar */}
      {showDebug && renderDebugPanel && renderDebugPanel({ messages })}
    </div>
  );
}
