"use client";

import { useEffect, useRef } from "react";
import { useToast } from "@/components/error/toast";
import type { ChatMessage } from "@/types/chat";

/**
 * Hook that automatically shows toast notifications when messages are truncated.
 * Should be used in components that display chat messages.
 */
export function useTruncationToast(messages: ChatMessage[]) {
  const { addToast } = useToast();
  const notifiedMessagesRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    // Find the latest assistant message that was truncated
    const latestTruncated = messages
      .filter(
        (m) =>
          m.role === "assistant" &&
          m.truncated &&
          !notifiedMessagesRef.current.has(m.id),
      )
      .pop();

    if (latestTruncated) {
      // Mark as notified to prevent duplicate toasts
      notifiedMessagesRef.current.add(latestTruncated.id);

      // Format the message
      const tokenInfo =
        latestTruncated.outputTokens && latestTruncated.maxTokensRequested
          ? `${latestTruncated.outputTokens.toLocaleString()}/${latestTruncated.maxTokensRequested.toLocaleString()} tokens`
          : undefined;

      addToast({
        type: "warning",
        title: "Response truncated",
        message: tokenInfo
          ? `Output limit reached at ${tokenInfo}. Consider increasing max_tokens.`
          : latestTruncated.truncationWarning ||
            "The response was cut short due to token limits.",
        duration: 8000,
        action: {
          label: "View details",
          onClick: () => {
            // Scroll to the truncated message indicator
            const messageElement = document.getElementById(
              `msg-${latestTruncated.id}`,
            );
            if (messageElement) {
              messageElement.scrollIntoView({
                behavior: "smooth",
                block: "center",
              });
              // Find and click the truncation indicator to expand it
              const indicator = messageElement.querySelector(
                "[data-truncation-indicator]",
              );
              if (indicator instanceof HTMLButtonElement) {
                indicator.click();
              }
            }
          },
        },
      });
    }
  }, [messages, addToast]);
}

/**
 * Convenience function to show a truncation toast manually.
 * Use this when you need to show a toast outside of the automatic hook.
 */
export function showTruncationToast(
  addToast: (toast: {
    type: "warning";
    title: string;
    message?: string;
    duration?: number;
    action?: { label: string; onClick: () => void };
  }) => string,
  options: {
    outputTokens?: number;
    maxTokensRequested?: number;
    truncationWarning?: string;
  },
) {
  const tokenInfo =
    options.outputTokens && options.maxTokensRequested
      ? `${options.outputTokens.toLocaleString()}/${options.maxTokensRequested.toLocaleString()} tokens`
      : undefined;

  return addToast({
    type: "warning",
    title: "Response truncated",
    message: tokenInfo
      ? `Output limit reached at ${tokenInfo}. Consider increasing max_tokens.`
      : options.truncationWarning ||
        "The response was cut short due to token limits.",
    duration: 8000,
  });
}
