"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { X, AlertTriangle, Send, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";

const FEEDBACK_CATEGORIES = [
  { id: "incorrect", label: "Incorrect information", icon: "!" },
  { id: "unhelpful", label: "Not helpful", icon: "?" },
  { id: "incomplete", label: "Incomplete response", icon: "..." },
  { id: "offensive", label: "Inappropriate content", icon: "⚠" },
  { id: "other", label: "Other issue", icon: "•" },
] as const;

type FeedbackCategory = (typeof FEEDBACK_CATEGORIES)[number]["id"];

interface FeedbackModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (feedback: {
    messageId: string;
    category: FeedbackCategory;
    details: string;
  }) => void;
  messageId: string;
  messagePreview?: string;
}

export function FeedbackModal({
  isOpen,
  onClose,
  onSubmit,
  messageId,
  messagePreview,
}: FeedbackModalProps) {
  const [selectedCategory, setSelectedCategory] =
    useState<FeedbackCategory | null>(null);
  const [details, setDetails] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setSelectedCategory(null);
      setDetails("");
      setIsSubmitted(false);
      // Focus textarea after animation
      setTimeout(() => textareaRef.current?.focus(), 100);
    }
  }, [isOpen]);

  // Close on escape
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) onClose();
    };
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [isOpen, onClose]);

  // Close on outside click
  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) onClose();
    },
    [onClose],
  );

  const handleSubmit = async () => {
    if (!selectedCategory) return;

    setIsSubmitting(true);
    try {
      await onSubmit({
        messageId,
        category: selectedCategory,
        details: details.trim(),
      });
      setIsSubmitted(true);
      // Auto-close after success animation
      setTimeout(() => {
        onClose();
      }, 1500);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className={cn(
        "fixed inset-0 z-50 flex items-center justify-center",
        "bg-slate-950/60 backdrop-blur-sm",
        "animate-in fade-in duration-200",
      )}
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby="feedback-modal-title"
    >
      <div
        ref={modalRef}
        data-testid="feedback-modal"
        className={cn(
          "relative w-full max-w-lg mx-4",
          "bg-white dark:bg-slate-900",
          "border border-slate-200 dark:border-slate-700",
          "rounded-xl shadow-2xl shadow-slate-900/20 dark:shadow-slate-950/50",
          "animate-in zoom-in-95 slide-in-from-bottom-4 duration-200",
        )}
      >
        {/* Terminal-style header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            <h2
              id="feedback-modal-title"
              className="text-sm font-semibold text-slate-900 dark:text-slate-100 font-mono"
            >
              FEEDBACK.REPORT
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
            aria-label="Close modal"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {isSubmitted ? (
          // Success state
          <div className="flex flex-col items-center justify-center py-12 px-6">
            <div className="relative">
              <CheckCircle2 className="h-12 w-12 text-emerald-500 animate-in zoom-in duration-300" />
              <span className="absolute inset-0 animate-ping-once">
                <CheckCircle2 className="h-12 w-12 text-emerald-500/30" />
              </span>
            </div>
            <p className="mt-4 text-sm font-medium text-slate-700 dark:text-slate-300">
              Feedback received
            </p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400 font-mono">
              LOGGED: {new Date().toISOString().slice(0, 19)}
            </p>
          </div>
        ) : (
          <div className="p-4">
            {/* Message preview */}
            {messagePreview && (
              <div className="mb-4 p-3 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
                <p className="text-xs text-slate-500 dark:text-slate-400 font-mono mb-1">
                  RE: MESSAGE_{messageId.slice(0, 8)}
                </p>
                <p className="text-sm text-slate-600 dark:text-slate-300 line-clamp-2">
                  {messagePreview}
                </p>
              </div>
            )}

            {/* Category selection - industrial toggle buttons */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-2 font-mono">
                CATEGORY.SELECT:
              </label>
              <div className="grid grid-cols-2 gap-2">
                {FEEDBACK_CATEGORIES.map((category) => (
                  <button
                    key={category.id}
                    data-testid={`feedback-category-${category.id}`}
                    onClick={() => setSelectedCategory(category.id)}
                    className={cn(
                      "relative flex items-center gap-2 px-3 py-2 rounded-lg",
                      "border text-sm text-left transition-all duration-150",
                      "focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/50",
                      selectedCategory === category.id
                        ? [
                            "border-amber-400 dark:border-amber-500",
                            "bg-amber-50 dark:bg-amber-950/30",
                            "text-amber-700 dark:text-amber-300",
                            "shadow-sm shadow-amber-200/50 dark:shadow-amber-900/30",
                          ]
                        : [
                            "border-slate-200 dark:border-slate-700",
                            "bg-white dark:bg-slate-800",
                            "text-slate-600 dark:text-slate-400",
                            "hover:border-slate-300 dark:hover:border-slate-600",
                            "hover:bg-slate-50 dark:hover:bg-slate-700/50",
                          ],
                    )}
                  >
                    <span
                      className={cn(
                        "flex items-center justify-center w-5 h-5 rounded text-xs font-mono font-bold",
                        selectedCategory === category.id
                          ? "bg-amber-200 dark:bg-amber-800 text-amber-700 dark:text-amber-200"
                          : "bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400",
                      )}
                    >
                      {category.icon}
                    </span>
                    <span className="font-medium">{category.label}</span>
                    {/* Selection indicator */}
                    {selectedCategory === category.id && (
                      <span className="absolute right-2 w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                    )}
                  </button>
                ))}
              </div>
            </div>

            {/* Details textarea */}
            <div className="mb-4">
              <label
                htmlFor="feedback-details"
                className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-2 font-mono"
              >
                DETAILS.INPUT:{" "}
                <span className="text-slate-400">(optional)</span>
              </label>
              <textarea
                ref={textareaRef}
                id="feedback-details"
                value={details}
                onChange={(e) => setDetails(e.target.value)}
                placeholder="What went wrong? How could the response be improved?"
                rows={3}
                className={cn(
                  "w-full px-3 py-2 rounded-lg resize-none",
                  "border border-slate-200 dark:border-slate-700",
                  "bg-white dark:bg-slate-800",
                  "text-sm text-slate-900 dark:text-slate-100",
                  "placeholder:text-slate-400 dark:placeholder:text-slate-500",
                  "focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400",
                  "transition-shadow duration-150",
                )}
              />
              <p className="mt-1 text-xs text-slate-400 dark:text-slate-500 font-mono">
                CHAR.COUNT: {details.length}/500
              </p>
            </div>

            {/* Submit button */}
            <button
              onClick={handleSubmit}
              disabled={!selectedCategory || isSubmitting}
              className={cn(
                "w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg",
                "font-medium text-sm transition-all duration-150",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
                selectedCategory
                  ? [
                      "bg-amber-500 hover:bg-amber-600 text-white",
                      "focus-visible:ring-amber-500",
                      "shadow-lg shadow-amber-500/25 hover:shadow-amber-500/40",
                    ]
                  : [
                      "bg-slate-100 dark:bg-slate-800 text-slate-400",
                      "cursor-not-allowed",
                    ],
              )}
            >
              {isSubmitting ? (
                <>
                  <span className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  TRANSMITTING...
                </>
              ) : (
                <>
                  <Send className="h-4 w-4" />
                  SUBMIT FEEDBACK
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
