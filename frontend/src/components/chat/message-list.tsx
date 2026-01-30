"use client";

import { Suspense, useEffect, useRef } from "react";
import type { ChatMessage } from "@/types/chat";
import { MessageBubble } from "./MessageBubble";
import { groupMessages } from "./message-utils";

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  onEditMessage?: (messageId: string, newContent: string) => void;
  onRegenerateMessage?: (messageId: string) => void;
  onContinueAs?: (model: string, prompt: string) => void;
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
  onContinueAs,
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

  const groupedMessages = groupMessages(messages);

  return (
    <>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {groupedMessages.map((item, index) => {
          if (Array.isArray(item)) {
            // Parallel response group
            return (
              <div key={item[0].responseGroupId} className="flex flex-col md:flex-row gap-3">
                {item.map((message) => (
                  <div key={message.id} className="flex-1 min-w-0">
                    <MessageBubble
                      message={message}
                      isStreaming={isStreaming && message.role === "assistant" && !message.content}
                      onEdit={onEditMessage}
                      onRegenerate={onRegenerateMessage}
                      onContinueAs={onContinueAs}
                      canEdit={!isStreaming}
                      canRegenerate={!isStreaming}
                    />
                  </div>
                ))}
              </div>
            );
          }
          // Single message
          const message = item;
          const isLastMessage = index === groupedMessages.length - 1;
          return (
            <MessageBubble
              key={message.id}
              message={message}
              isStreaming={
                isStreaming &&
                message.role === "assistant" &&
                isLastMessage
              }
              onEdit={onEditMessage}
              onRegenerate={onRegenerateMessage}
              onContinueAs={onContinueAs}
              canEdit={!isStreaming}
              canRegenerate={!isStreaming}
            />
          );
        })}
        <div ref={bottomRef} />
      </div>
    </>
  );
}
