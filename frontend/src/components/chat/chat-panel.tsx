"use client";

import { useChatStream } from "@/hooks/use-chat-stream";
import { DegradedModeBanner } from "@/components/degraded-mode-banner";
import { MessageList } from "./message-list";
import { MessageInput } from "./message-input";

interface ChatPanelProps {
  model?: string;
  sessionId?: string;
}

/**
 * Main chat panel component with streaming and cancellation support.
 */
export function ChatPanel({ model, sessionId }: ChatPanelProps) {
  const { messages, status, error, sendMessage, cancelStream, clearMessages } =
    useChatStream({ model, sessionId });

  const isStreaming = status === "streaming" || status === "cancelling";

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-700 px-4 py-3">
        <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
          Agent Hub
        </h1>
        <div className="flex items-center gap-3">
          {/* Status indicator */}
          <div className="flex items-center gap-2 text-sm">
            <span
              className={`w-2 h-2 rounded-full ${
                status === "idle"
                  ? "bg-green-500"
                  : status === "streaming"
                    ? "bg-blue-500 animate-pulse"
                    : status === "cancelling"
                      ? "bg-yellow-500 animate-pulse"
                      : status === "error"
                        ? "bg-red-500"
                        : "bg-gray-400"
              }`}
            />
            <span className="text-gray-500 dark:text-gray-400 capitalize">
              {status}
            </span>
          </div>

          {/* Clear button */}
          {messages.length > 0 && !isStreaming && (
            <button
              onClick={clearMessages}
              className="text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            >
              Clear
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
      <MessageList messages={messages} isStreaming={isStreaming} />

      {/* Input */}
      <MessageInput
        onSend={sendMessage}
        onCancel={cancelStream}
        status={status}
      />
    </div>
  );
}
