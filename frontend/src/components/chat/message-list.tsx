"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/types/chat";
import { cn } from "@/lib/utils";

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
}

export function MessageList({ messages, isStreaming }: MessageListProps) {
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
      {messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          isStreaming={
            isStreaming &&
            message.role === "assistant" &&
            message === messages[messages.length - 1]
          }
        />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

interface MessageBubbleProps {
  message: ChatMessage;
  isStreaming: boolean;
}

function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div
      className={cn("flex", isUser ? "justify-end" : "justify-start")}
    >
      <div
        className={cn(
          "max-w-[80%] rounded-lg px-4 py-2",
          isUser
            ? "bg-blue-500 text-white"
            : "bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100",
          message.cancelled && "border-2 border-yellow-500"
        )}
      >
        <div className="whitespace-pre-wrap break-words">
          {message.content}
          {isStreaming && (
            <span className="inline-block w-2 h-4 ml-1 bg-current animate-pulse" />
          )}
        </div>

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
      </div>
    </div>
  );
}
