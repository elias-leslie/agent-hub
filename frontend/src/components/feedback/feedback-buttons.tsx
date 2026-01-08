"use client";

import { useState, useCallback } from "react";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import { cn } from "@/lib/utils";

export type FeedbackType = "positive" | "negative" | null;

interface FeedbackButtonsProps {
  messageId: string;
  initialFeedback?: FeedbackType;
  onFeedback?: (messageId: string, type: FeedbackType, details?: string) => void;
  onNegativeFeedback?: (messageId: string) => void;
  disabled?: boolean;
  className?: string;
}

export function FeedbackButtons({
  messageId,
  initialFeedback = null,
  onFeedback,
  onNegativeFeedback,
  disabled = false,
  className,
}: FeedbackButtonsProps) {
  const [feedback, setFeedback] = useState<FeedbackType>(initialFeedback);
  const [animating, setAnimating] = useState<"positive" | "negative" | null>(null);

  const handleFeedback = useCallback(
    (type: FeedbackType) => {
      if (disabled) return;

      // Toggle if clicking same button
      const newFeedback = feedback === type ? null : type;

      // Trigger animation
      setAnimating(type);
      setTimeout(() => setAnimating(null), 300);

      setFeedback(newFeedback);
      onFeedback?.(messageId, newFeedback);

      // Open feedback modal for negative feedback
      if (newFeedback === "negative") {
        onNegativeFeedback?.(messageId);
      }
    },
    [feedback, messageId, onFeedback, onNegativeFeedback, disabled]
  );

  return (
    <div
      className={cn(
        "inline-flex items-center gap-0.5 p-0.5 rounded-md",
        "bg-slate-100/50 dark:bg-slate-800/50",
        "border border-slate-200/50 dark:border-slate-700/50",
        className
      )}
    >
      {/* Positive feedback button */}
      <button
        onClick={() => handleFeedback("positive")}
        disabled={disabled}
        className={cn(
          "relative p-1.5 rounded transition-all duration-150",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/50",
          "disabled:opacity-40 disabled:cursor-not-allowed",
          // Base state
          feedback !== "positive" && [
            "text-slate-400 dark:text-slate-500",
            "hover:text-amber-500 dark:hover:text-amber-400",
            "hover:bg-amber-50 dark:hover:bg-amber-950/30",
          ],
          // Active state
          feedback === "positive" && [
            "text-amber-500 dark:text-amber-400",
            "bg-amber-100 dark:bg-amber-900/40",
            "shadow-inner shadow-amber-200/50 dark:shadow-amber-900/50",
          ],
          // Click animation
          animating === "positive" && "scale-110"
        )}
        title="Good response"
        aria-label="Mark as good response"
        aria-pressed={feedback === "positive"}
      >
        <ThumbsUp
          className={cn(
            "h-3.5 w-3.5 transition-transform duration-150",
            animating === "positive" && "animate-bounce-once"
          )}
          strokeWidth={feedback === "positive" ? 2.5 : 2}
        />
        {/* Mechanical press indicator */}
        {feedback === "positive" && (
          <span className="absolute inset-0 rounded bg-amber-400/20 animate-ping-once" />
        )}
      </button>

      {/* Divider */}
      <span className="w-px h-4 bg-slate-200 dark:bg-slate-700" />

      {/* Negative feedback button */}
      <button
        onClick={() => handleFeedback("negative")}
        disabled={disabled}
        className={cn(
          "relative p-1.5 rounded transition-all duration-150",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500/50",
          "disabled:opacity-40 disabled:cursor-not-allowed",
          // Base state
          feedback !== "negative" && [
            "text-slate-400 dark:text-slate-500",
            "hover:text-red-500 dark:hover:text-red-400",
            "hover:bg-red-50 dark:hover:bg-red-950/30",
          ],
          // Active state
          feedback === "negative" && [
            "text-red-500 dark:text-red-400",
            "bg-red-100 dark:bg-red-900/40",
            "shadow-inner shadow-red-200/50 dark:shadow-red-900/50",
          ],
          // Click animation
          animating === "negative" && "scale-110"
        )}
        title="Poor response"
        aria-label="Mark as poor response"
        aria-pressed={feedback === "negative"}
      >
        <ThumbsDown
          className={cn(
            "h-3.5 w-3.5 transition-transform duration-150",
            animating === "negative" && "animate-bounce-once"
          )}
          strokeWidth={feedback === "negative" ? 2.5 : 2}
        />
        {feedback === "negative" && (
          <span className="absolute inset-0 rounded bg-red-400/20 animate-ping-once" />
        )}
      </button>
    </div>
  );
}
