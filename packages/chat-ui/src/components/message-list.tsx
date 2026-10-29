"use client";

import { Suspense, useCallback, useEffect, useRef } from "react";
import type { ChatMessage } from "../types/chat";
import { MessageBubble } from "./MessageBubble";
import { groupMessages } from "./message-utils";
import { TranscriptMessage } from "./transcript/TranscriptMessage";

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  onEditMessage?: (messageId: string, newContent: string) => void;
  onRegenerateMessage?: (messageId: string) => void;
  onContinueMessage?: (messageId: string) => void;
  onContinueAs?: (model: string, prompt: string) => void;
  /** Shown when there are no messages; a host that failed to load them says so here instead of "Start a conversation". */
  emptyLabel?: string;
  /** Follow-ups the host holds until the running turn ends. Shown after the messages, marked "Queued". */
  queued?: string[];
  /** `transcript` is one centred reading column: no bubbles, no cards, tool calls as lines. */
  variant?: "default" | "transcript";
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
    <div className="flex-1 flex items-center justify-center text-muted-foreground">
      <p>Loading messages...</p>
    </div>
  );
}

function MessageListInner({
  messages,
  isStreaming,
  onEditMessage,
  onRegenerateMessage,
  onContinueMessage,
  onContinueAs,
  emptyLabel = "Start a conversation",
  queued = [],
  variant = "default",
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stuck = useRef(true);
  const transcript = variant === "transcript";

  useEffect(() => {
    if (transcript) {
      // Follow the newest line only while the reader is at the bottom; scrolling up to read stays put.
      const el = scrollRef.current;
      if (messages[messages.length - 1]?.role === "user") stuck.current = true;
      if (el && stuck.current) el.scrollTop = el.scrollHeight;
      return;
    }
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, queued.length, transcript]);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (el) stuck.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  }, []);

  if (messages.length === 0 && queued.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        <p>{emptyLabel}</p>
      </div>
    );
  }

  if (transcript) {
    return (
      <div ref={scrollRef} onScroll={onScroll} data-testid="transcript" className="min-h-0 flex-1 overflow-y-auto py-[18px]">
        <div className="mx-auto w-full max-w-[860px] px-5">
          {messages.map((message, index) => (
            <TranscriptMessage
              key={message.id}
              message={message}
              isStreaming={isStreaming && message.role === "assistant" && index === messages.length - 1}
            />
          ))}
        </div>
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
                      onContinue={onContinueMessage}
                      onContinueAs={onContinueAs}
                      canEdit={!isStreaming}
                      canRegenerate={!isStreaming}
                      canContinue={!isStreaming}
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
              onContinue={onContinueMessage}
              onContinueAs={onContinueAs}
              canEdit={!isStreaming}
              canRegenerate={!isStreaming}
              canContinue={!isStreaming}
            />
          );
        })}
        {queued.length > 0 ? (
          <ul aria-label="Queued messages" className="space-y-2">
            {queued.map((text, index) => (
              <li key={`${index}:${text}`} data-testid="queued-message" className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl border border-dashed border-border bg-muted/40 px-4 py-2 text-sm text-foreground/80">
                  <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    Queued
                  </span>
                  <p className="whitespace-pre-wrap break-words">{text}</p>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
        <div ref={bottomRef} />
      </div>
    </>
  );
}
