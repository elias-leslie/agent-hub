"use client";

import { useEffect, useRef, useState } from "react";
import {
  Pencil,
  RefreshCw,
  Check,
  X,
  History,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import type { ChatMessage } from "@/types/chat";
import { cn } from "@/lib/utils";

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  onEditMessage?: (messageId: string, newContent: string) => void;
  onRegenerateMessage?: (messageId: string) => void;
}

export function MessageList({
  messages,
  isStreaming,
  onEditMessage,
  onRegenerateMessage,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500 dark:text-gray-400">
        <p>Start a conversation</p>
      </div>
    );
  }

  return (
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
          canEdit={!isStreaming}
          canRegenerate={!isStreaming}
        />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

interface MessageBubbleProps {
  message: ChatMessage;
  isStreaming: boolean;
  onEdit?: (messageId: string, newContent: string) => void;
  onRegenerate?: (messageId: string) => void;
  canEdit: boolean;
  canRegenerate: boolean;
}

function MessageBubble({
  message,
  isStreaming,
  onEdit,
  onRegenerate,
  canEdit,
  canRegenerate,
}: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(message.content);
  const [showHistory, setShowHistory] = useState(false);
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
      className={cn("flex group", isUser ? "justify-end" : "justify-start")}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className="flex items-start gap-2 max-w-[85%]">
        {/* Action buttons for assistant (left side) */}
        {!isUser && !isStreaming && (
          <div
            className={cn(
              "flex flex-col gap-1 pt-2 transition-opacity duration-200",
              isHovered ? "opacity-100" : "opacity-0"
            )}
          >
            {onRegenerate && canRegenerate && (
              <button
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
              : "bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100",
            message.cancelled && "border-2 border-yellow-500"
          )}
        >
          {isEditing ? (
            <div className="space-y-2">
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                className={cn(
                  "w-full min-w-[200px] px-2 py-1 rounded text-sm resize-none focus:outline-none focus:ring-2",
                  isUser
                    ? "bg-blue-400 text-white placeholder-blue-200 focus:ring-blue-300"
                    : "bg-white dark:bg-gray-900 focus:ring-blue-500"
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
                      : "hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500"
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
                      : "hover:bg-gray-200 dark:hover:bg-gray-700 text-emerald-600 dark:text-emerald-400"
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
                  {message.previousVersions && message.previousVersions.length > 0 && (
                    <button
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

              {(message.inputTokens !== undefined ||
                message.outputTokens !== undefined) && (
                <div className="mt-2 text-xs opacity-60">
                  {message.inputTokens && <span>In: {message.inputTokens} </span>}
                  {message.outputTokens && <span>Out: {message.outputTokens}</span>}
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
              isHovered ? "opacity-100" : "opacity-0"
            )}
          >
            {onEdit && canEdit && (
              <button
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
