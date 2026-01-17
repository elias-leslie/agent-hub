"use client";

import { KeyboardEvent, useState } from "react";
import { Send, Square } from "lucide-react";
import type { StreamStatus } from "@/types/chat";
import { cn } from "@/lib/utils";

interface MessageInputProps {
  onSend: (message: string) => void;
  onCancel: () => void;
  status: StreamStatus;
  disabled?: boolean;
}

/**
 * Message input with Send/Stop button that toggles based on streaming state.
 *
 * - Shows Send button when idle
 * - Shows Stop button during streaming
 * - Pressing Stop triggers cancellation
 */
export function MessageInput({
  onSend,
  onCancel,
  status,
  disabled = false,
}: MessageInputProps) {
  const [input, setInput] = useState("");

  const isStreaming = status === "streaming" || status === "cancelling";
  const isCancelling = status === "cancelling";
  const canSend = !isStreaming && !disabled && input.trim().length > 0;
  const canCancel = status === "streaming";

  const handleSend = () => {
    if (!canSend) return;
    onSend(input.trim());
    setInput("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border-t border-gray-200 dark:border-gray-700 p-4">
      <div className="flex items-end gap-2">
        <textarea
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isStreaming ? "Waiting for response..." : "Type a message..."}
          disabled={isStreaming || disabled}
          rows={1}
          className={cn(
            "flex-1 resize-none rounded-lg border border-gray-300 dark:border-gray-600",
            "bg-white dark:bg-gray-800 px-4 py-2",
            "focus:outline-none focus:ring-2 focus:ring-blue-500",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "min-h-[40px] max-h-[120px]"
          )}
          style={{
            height: "auto",
            overflow: input.split("\n").length > 3 ? "auto" : "hidden",
          }}
        />

        {isStreaming ? (
          <button
            data-testid="stop-button"
            onClick={onCancel}
            disabled={!canCancel}
            aria-label="Stop generating"
            title="Stop generating"
            className={cn(
              "flex items-center justify-center w-10 h-10 rounded-lg",
              "transition-colors duration-150",
              canCancel
                ? "bg-red-500 hover:bg-red-600 text-white cursor-pointer"
                : "bg-gray-300 dark:bg-gray-600 text-gray-500 cursor-not-allowed",
              isCancelling && "animate-pulse"
            )}
          >
            <Square className="w-5 h-5" fill="currentColor" />
          </button>
        ) : (
          <button
            data-testid="send-button"
            onClick={handleSend}
            disabled={!canSend}
            aria-label="Send message"
            title="Send message"
            className={cn(
              "flex items-center justify-center w-10 h-10 rounded-lg",
              "transition-colors duration-150",
              canSend
                ? "bg-blue-500 hover:bg-blue-600 text-white cursor-pointer"
                : "bg-gray-300 dark:bg-gray-600 text-gray-500 cursor-not-allowed"
            )}
          >
            <Send className="w-5 h-5" />
          </button>
        )}
      </div>

      {status === "error" && (
        <p className="mt-2 text-sm text-red-500">
          Connection error. Please try again.
        </p>
      )}
    </div>
  );
}
