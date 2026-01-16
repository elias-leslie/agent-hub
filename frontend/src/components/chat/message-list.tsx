"use client";

import { Suspense, useEffect, useRef, useState, useCallback } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import {
  Pencil,
  RefreshCw,
  Check,
  X,
  History,
  ChevronDown,
  ChevronUp,
  Cpu,
  Sparkles,
  Brain,
} from "lucide-react";
import type { ChatMessage } from "@/types/chat";
import { cn } from "@/lib/utils";
import {
  FeedbackButtons,
  FeedbackModal,
  type FeedbackType,
} from "@/components/feedback";
import { TruncationIndicator } from "./truncation-indicator";

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  onEditMessage?: (messageId: string, newContent: string) => void;
  onRegenerateMessage?: (messageId: string) => void;
  onFeedback?: (
    messageId: string,
    type: FeedbackType,
    details?: string,
  ) => void;
  onFeedbackSubmit?: (feedback: {
    messageId: string;
    category: string;
    details: string;
  }) => void;
}

export function MessageList(props: MessageListProps) {
  return (
    <Suspense fallback={<MessageListFallback />}>
      <MessageListInner {...props} />
    </Suspense>
  );
}

function MessageListFallback() {
  return (
    <div className="flex-1 flex items-center justify-center text-gray-500 dark:text-gray-400">
      <p>Loading messages...</p>
    </div>
  );
}

function MessageListInner({
  messages,
  isStreaming,
  onEditMessage,
  onRegenerateMessage,
  onFeedback,
  onFeedbackSubmit,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  // URL param controlled state for feedback modal
  const modalParam = searchParams.get("modal");
  const messageParam = searchParams.get("message");
  const feedbackModalOpen = modalParam === "feedback" && !!messageParam;
  const feedbackMessageId = feedbackModalOpen ? messageParam : null;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const openFeedbackModal = useCallback(
    (messageId: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("modal", "feedback");
      params.set("message", messageId);
      router.push(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  const closeFeedbackModal = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("modal");
    params.delete("message");
    const newUrl = params.toString()
      ? `${pathname}?${params.toString()}`
      : pathname;
    router.push(newUrl, { scroll: false });
  }, [router, pathname, searchParams]);

  const handleNegativeFeedback = useCallback(
    (messageId: string) => {
      openFeedbackModal(messageId);
    },
    [openFeedbackModal],
  );

  const handleFeedbackSubmit = useCallback(
    (feedback: { messageId: string; category: string; details: string }) => {
      onFeedbackSubmit?.(feedback);
    },
    [onFeedbackSubmit],
  );

  const feedbackMessage = feedbackMessageId
    ? messages.find((m) => m.id === feedbackMessageId)
    : null;

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500 dark:text-gray-400">
        <p>Start a conversation</p>
      </div>
    );
  }

  return (
    <>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message, index) => (
          <MessageBubble
            key={message.id}
            message={message}
            isStreaming={
              isStreaming &&
              message.role === "assistant" &&
              index === messages.length - 1
            }
            onEdit={onEditMessage}
            onRegenerate={onRegenerateMessage}
            onFeedback={onFeedback}
            onNegativeFeedback={handleNegativeFeedback}
            canEdit={!isStreaming}
            canRegenerate={!isStreaming}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Feedback Modal */}
      <FeedbackModal
        isOpen={feedbackModalOpen}
        onClose={closeFeedbackModal}
        onSubmit={handleFeedbackSubmit}
        messageId={feedbackMessageId || ""}
        messagePreview={feedbackMessage?.content?.slice(0, 200)}
      />
    </>
  );
}

interface MessageBubbleProps {
  message: ChatMessage;
  isStreaming: boolean;
  onEdit?: (messageId: string, newContent: string) => void;
  onRegenerate?: (messageId: string) => void;
  onFeedback?: (
    messageId: string,
    type: FeedbackType,
    details?: string,
  ) => void;
  onNegativeFeedback?: (messageId: string) => void;
  canEdit: boolean;
  canRegenerate: boolean;
}

function MessageBubble({
  message,
  isStreaming,
  onEdit,
  onRegenerate,
  onFeedback,
  onNegativeFeedback,
  canEdit,
  canRegenerate,
}: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(message.content);
  const [showHistory, setShowHistory] = useState(false);
  const [showThinking, setShowThinking] = useState(false);
  const [isHovered, setIsHovered] = useState(false);

  const handleSaveEdit = () => {
    if (onEdit && editContent.trim() !== message.content) {
      onEdit(message.id, editContent.trim());
    }
    setIsEditing(false);
  };

  const handleCancelEdit = () => {
    setEditContent(message.content);
    setIsEditing(false);
  };

  const handleStartEdit = () => {
    setEditContent(message.content);
    setIsEditing(true);
  };

  return (
    <div
      id={`msg-${message.id}`}
      className={cn("flex group", isUser ? "justify-end" : "justify-start")}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className="flex items-start gap-2 max-w-[85%]">
        {/* Action buttons for assistant (left side) */}
        {!isUser && !isStreaming && (
          <div
            data-testid="message-actions"
            className={cn(
              "flex flex-col gap-1 pt-2 transition-opacity duration-200",
              isHovered ? "opacity-100" : "opacity-0",
            )}
          >
            {onRegenerate && canRegenerate && (
              <button
                data-testid="regenerate-btn"
                onClick={() => onRegenerate(message.id)}
                className="p-1.5 rounded-md hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                title="Regenerate response"
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        )}

        {/* Message bubble */}
        <div
          className={cn(
            "rounded-lg px-4 py-2 relative",
            isUser
              ? "bg-blue-500 text-white"
              : message.agentProvider === "claude"
                ? "bg-gradient-to-br from-orange-50 to-amber-50/50 border border-orange-100 dark:from-orange-950/30 dark:to-amber-950/20 dark:border-orange-900/30 text-gray-900 dark:text-gray-100"
                : message.agentProvider === "gemini"
                  ? "bg-gradient-to-br from-blue-50 to-indigo-50/50 border border-blue-100 dark:from-blue-950/30 dark:to-indigo-950/20 dark:border-blue-900/30 text-gray-900 dark:text-gray-100"
                  : "bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100",
            message.cancelled && "border-2 border-yellow-500",
          )}
        >
          {/* Agent badge for multi-agent messages */}
          {!isUser && message.agentName && (
            <div className="flex items-center gap-1.5 mb-2 pb-2 border-b border-current/10">
              {message.agentProvider === "claude" ? (
                <Cpu className="h-3.5 w-3.5 text-orange-500 dark:text-orange-400" />
              ) : message.agentProvider === "gemini" ? (
                <Sparkles className="h-3.5 w-3.5 text-blue-500 dark:text-blue-400" />
              ) : null}
              <span
                className={cn(
                  "text-xs font-semibold",
                  message.agentProvider === "claude"
                    ? "text-orange-600 dark:text-orange-400"
                    : message.agentProvider === "gemini"
                      ? "text-blue-600 dark:text-blue-400"
                      : "text-gray-600 dark:text-gray-400",
                )}
              >
                {message.agentName}
              </span>
              {message.isDeliberation && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-200/50 text-slate-500 dark:bg-slate-700/50 dark:text-slate-400">
                  deliberation
                </span>
              )}
              {message.isConsensus && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-600 dark:bg-emerald-900/50 dark:text-emerald-400 font-medium">
                  consensus
                </span>
              )}
            </div>
          )}
          {/* Extended thinking block */}
          {!isUser && message.thinking && (
            <div className="mb-3">
              <button
                data-testid="thinking-toggle"
                onClick={() => setShowThinking(!showThinking)}
                className="flex items-center gap-1.5 text-xs text-purple-600 dark:text-purple-400 hover:text-purple-700 dark:hover:text-purple-300 transition-colors"
              >
                <Brain
                  className={cn(
                    "h-3.5 w-3.5",
                    isStreaming && !message.content && "animate-pulse",
                  )}
                />
                <span className="font-medium">
                  {isStreaming && !message.content ? "Thinking..." : "Thinking"}
                </span>
                {!isStreaming && message.thinkingTokens && (
                  <span className="text-purple-400 dark:text-purple-500">
                    ({message.thinkingTokens.toLocaleString()} tokens)
                  </span>
                )}
                {showThinking ? (
                  <ChevronUp className="h-3 w-3" />
                ) : (
                  <ChevronDown className="h-3 w-3" />
                )}
              </button>
              {showThinking && (
                <div className="mt-2 p-3 rounded-md bg-purple-50 dark:bg-purple-950/30 border border-purple-100 dark:border-purple-900/50 text-sm text-purple-800 dark:text-purple-200 whitespace-pre-wrap">
                  {message.thinking}
                  {isStreaming && !message.content && (
                    <span className="inline-block w-2 h-4 ml-1 bg-purple-500 animate-pulse" />
                  )}
                </div>
              )}
            </div>
          )}
          {isEditing ? (
            <div className="space-y-2">
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                className={cn(
                  "w-full min-w-[200px] px-2 py-1 rounded text-sm resize-none focus:outline-none focus:ring-2",
                  isUser
                    ? "bg-blue-400 text-white placeholder-blue-200 focus:ring-blue-300"
                    : "bg-white dark:bg-gray-900 focus:ring-blue-500",
                )}
                rows={Math.min(editContent.split("\n").length + 1, 10)}
                autoFocus
              />
              <div className="flex gap-2 justify-end">
                <button
                  onClick={handleCancelEdit}
                  className={cn(
                    "p-1 rounded",
                    isUser
                      ? "hover:bg-blue-400 text-blue-100"
                      : "hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500",
                  )}
                >
                  <X className="h-4 w-4" />
                </button>
                <button
                  onClick={handleSaveEdit}
                  className={cn(
                    "p-1 rounded",
                    isUser
                      ? "hover:bg-blue-400 text-white"
                      : "hover:bg-gray-200 dark:hover:bg-gray-700 text-emerald-600 dark:text-emerald-400",
                  )}
                >
                  <Check className="h-4 w-4" />
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="whitespace-pre-wrap break-words">
                {message.content}
                {isStreaming && (
                  <span className="inline-block w-2 h-4 ml-1 bg-current animate-pulse" />
                )}
              </div>

              {/* Edited indicator */}
              {message.edited && (
                <div className="mt-1 flex items-center gap-1 text-xs opacity-60">
                  <Pencil className="h-3 w-3" />
                  <span>edited</span>
                  {message.previousVersions &&
                    message.previousVersions.length > 0 && (
                      <button
                        data-testid="history-toggle"
                        onClick={() => setShowHistory(!showHistory)}
                        className="ml-1 flex items-center gap-0.5 hover:opacity-80"
                      >
                        <History className="h-3 w-3" />
                        {showHistory ? (
                          <ChevronUp className="h-3 w-3" />
                        ) : (
                          <ChevronDown className="h-3 w-3" />
                        )}
                      </button>
                    )}
                </div>
              )}

              {/* Version history */}
              {showHistory && message.previousVersions && (
                <div className="mt-2 pt-2 border-t border-current/20 text-xs opacity-60 space-y-1">
                  <p className="font-medium">Previous versions:</p>
                  {message.previousVersions.map((version, i) => (
                    <p key={i} className="pl-2 border-l-2 border-current/30">
                      {version}
                    </p>
                  ))}
                </div>
              )}

              {message.cancelled && (
                <div className="mt-2 text-xs text-yellow-600 dark:text-yellow-400 font-medium">
                  [cancelled]
                </div>
              )}

              {/* Truncation indicator with visual gauge */}
              {message.truncated && (
                <TruncationIndicator
                  outputTokens={message.outputTokens}
                  maxTokensRequested={message.maxTokensRequested}
                  modelLimit={message.modelLimit}
                  truncationWarning={message.truncationWarning}
                />
              )}

              {(message.inputTokens !== undefined ||
                message.outputTokens !== undefined) && (
                <div className="mt-2 text-xs opacity-60">
                  {message.inputTokens && (
                    <span>In: {message.inputTokens} </span>
                  )}
                  {message.outputTokens && (
                    <span>Out: {message.outputTokens}</span>
                  )}
                </div>
              )}

              {/* Feedback buttons for assistant messages */}
              {!isUser && !isStreaming && (
                <div className="mt-3 pt-2 border-t border-current/10 flex items-center justify-between">
                  <span className="text-xs text-slate-400 dark:text-slate-500">
                    Was this helpful?
                  </span>
                  <FeedbackButtons
                    messageId={message.id}
                    onFeedback={onFeedback}
                    onNegativeFeedback={onNegativeFeedback}
                    disabled={isStreaming}
                  />
                </div>
              )}
            </>
          )}
        </div>

        {/* Action buttons for user (right side) */}
        {isUser && !isStreaming && !isEditing && (
          <div
            className={cn(
              "flex flex-col gap-1 pt-2 transition-opacity duration-200",
              isHovered ? "opacity-100" : "opacity-0",
            )}
          >
            {onEdit && canEdit && (
              <button
                data-testid="edit-btn"
                onClick={handleStartEdit}
                className="p-1.5 rounded-md hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                title="Edit message"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
