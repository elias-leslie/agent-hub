"use client";

import { useMemo, useState, useRef, useCallback, useEffect } from "react";
import {
  Archive,
  CornerDownRight,
  PanelRight,
  PanelRightClose,
  Play,
  Shuffle,
  Split,
} from "lucide-react";
import { ChatClientProvider, useRequiredChatClient, type ChatHubClient } from "../client";
import { useChatStream, type ChatStreamConfig } from "../hooks/use-chat-stream";
import { describePhase } from "../hooks/chat-stream/turn-phase";
import type { ChatMessage } from "../types/chat";
import type { ChatVoice } from "../types/voice";
import { MessageList } from "./message-list";
import { routeText } from "./MessageRuntimeDetails";
import { MessageInput } from "./message-input";
import { ActivityIndicator, type ActivityState } from "./activity-indicator";
import { QueuedChips } from "./transcript/QueuedChips";
import { StatusLine } from "./transcript/StatusLine";
import { sessionCost } from "./transcript/status-line";
import { describeTool } from "./transcript/tool-format";

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
  /**
   * `page` is the full chat page. `compact` drops the title header and toolbar for a small window: one status row
   * (activity, phase, model route, tokens) above the messages. `transcript` is the coding-chat look: one reading
   * column with no bubbles or cards, tool calls as lines, a bordered composer and a status line under it.
   */
  layout?: "page" | "compact" | "transcript";
  /** Transcript layout: controls for the composer's bar, left of Stop and Send (a model select). */
  renderComposerControls?: () => React.ReactNode;
  /** Transcript layout: the git branch for the status line, when the host knows it. Else the session's own, if it has one. */
  branch?: string | null;
  /** Offer @model mentions in the input. Default true. */
  allowModelMentions?: boolean;
  /** Voice input and output from `useChatVoice` (`@agent-hub/chat-ui/voice`). Omit for a chat without voice. */
  voice?: ChatVoice;
  /** When true, speak every assistant response (not just after voice input) */
  alwaysSpeak?: boolean;
  renderBanner?: () => React.ReactNode;
  renderDebugPanel?: (props: { messages: ChatMessage[] }) => React.ReactNode;
  onMessagesChange?: (messages: ChatMessage[]) => void;
}

/** The transcript header pill's wording per state: plain phase names, no trailing dots. */
const TRANSCRIPT_PILL: Record<ActivityState, string> = {
  idle: "Ready",
  connecting: "Connecting",
  waiting: "Waiting for the model",
  working: "Working",
  retrying: "Retrying",
  thinking: "Thinking",
  calling_tool: "Running a tool",
  streaming: "Responding",
  reconnecting: "Reconnecting",
  cancelling: "Stopping",
  error: "Error",
};

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
  layout = "page",
  renderComposerControls,
  branch,
  allowModelMentions = true,
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
    queued,
    sessionStats,
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

  const client = useRequiredChatClient();
  const transcript = layout === "transcript";
  const compact = layout === "compact";
  const allowQueue = Boolean(client.followUps);
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

  // One visible status, and it names the phase the turn is in. The phase text itself is kept for screen readers.
  const phaseLabel = isBusy ? describePhase(turnPhase) : null;
  const [phaseName, phaseDetail] = (status === "streaming" ? turnPhase ?? "" : "").split(":", 2);
  const pillState: ActivityState =
    status !== "streaming"
      ? (status as ActivityState)
      : phaseName === "waiting_for_model"
        ? "waiting"
        : phaseName === "thinking"
          ? "thinking"
          : phaseName === "running_tool"
            ? "calling_tool"
            : phaseName === "responding"
              ? "streaming"
              : phaseName === "retrying"
                ? "retrying"
                : "working";
  const pillLabel = pillState === "calling_tool" && phaseDetail ? `Calling ${phaseDetail}...` : undefined;

  const routeLabel = lastAssistantMessage ? routeText(lastAssistantMessage) : null;

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

  if (transcript) {
    const turns = messages.filter((m) => m.role === "user").length;
    const headerModel = lastAssistantMessage?.servedModel ?? lastAssistantMessage?.requestedModel;
    const transcriptPill =
      pillState === "calling_tool" && phaseDetail
        ? `Running ${describeTool({ name: phaseDetail, input: {} }).name}`
        : TRANSCRIPT_PILL[pillState];
    return (
      <div className="flex h-full min-w-0 flex-col">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-border px-3.5 py-2 text-xs text-muted-foreground">
          <ActivityIndicator state={pillState} label={transcriptPill} decorative={!!phaseLabel} size="sm" />
          {phaseLabel ? (
            <span data-testid="turn-phase" className="sr-only" aria-live="polite">
              {phaseLabel}
            </span>
          ) : null}
          {headerModel ? (
            <span data-testid="header-model" className="min-w-0 truncate font-mono text-[12.5px]">
              {headerModel}
            </span>
          ) : null}
          <span className="flex-1" />
          {turns > 0 ? <span className="font-mono">turn {turns}</span> : null}
        </div>

        {renderBanner?.()}

        {error && (
          <div role="alert" className="border-b border-destructive/30 bg-destructive/10 px-4 py-2">
            <p className="text-sm text-destructive">{error}</p>
          </div>
        )}

        <MessageList
          variant="transcript"
          messages={messages}
          isStreaming={isStreaming}
          emptyLabel={error ? "No messages loaded" : undefined}
        />

        <div className="border-t border-border px-3.5 pb-3 pt-2.5">
          <div className="mx-auto w-full max-w-[860px]">
            <QueuedChips queued={queued} />
            <MessageInput
              variant="transcript"
              controls={renderComposerControls?.()}
              agentSlug={agentSlug}
              onSend={sendMessage}
              onCancel={cancelStream}
              status={status}
              voice={voice}
              onVoiceSend={handleVoiceSend}
              initialPrompt={initialPrompt}
              allowModelMentions={allowModelMentions}
              allowQueue={allowQueue}
            />
            <StatusLine
              requestedModel={lastAssistantMessage?.requestedModel}
              servedModel={lastAssistantMessage?.servedModel}
              busy={isBusy}
              inputTokens={sessionStats.inputTokens}
              outputTokens={sessionStats.outputTokens}
              costUsd={sessionCost(messages) ?? sessionStats.costUsd}
              contextPercent={sessionStats.contextPercent}
              branch={branch ?? sessionStats.branch}
            />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-row h-full">
      <div className="flex flex-col flex-1 h-full min-w-0">
        {compact ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-card/35 px-3 py-1.5 text-xs text-muted-foreground">
            <ActivityIndicator state={pillState} label={pillLabel} decorative={!!phaseLabel} />
            {phaseLabel ? (
              <span data-testid="turn-phase" className="sr-only" aria-live="polite">
                {phaseLabel}
              </span>
            ) : null}
            {routeLabel ? (
              <span data-testid="model-route" className="truncate" title="Model asked for, and model that answered">
                {routeLabel}
              </span>
            ) : null}
            {lastAssistantMessage?.fallbackUsed ? (
              <span
                className="inline-flex items-center gap-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-amber-200"
                title={lastAssistantMessage.fallbackReason ?? "A fallback model answered"}
              >
                <Shuffle className="h-3 w-3" />
                fallback
              </span>
            ) : null}
            {tokenTotal > 0 ? <span>{tokenTotal.toLocaleString()} tokens</span> : null}
          </div>
        ) : (
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
              <ActivityIndicator state={pillState} label={pillLabel} decorative={!!phaseLabel} />
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
        )}

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
          queued={queued}
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
          compact={compact}
          allowModelMentions={allowModelMentions}
          allowQueue={allowQueue}
        />
      </div>

      {/* Debug Panel Sidebar */}
      {showDebug && renderDebugPanel && renderDebugPanel({ messages })}
    </div>
  );
}
