"use client";

import {
  Clock,
  CloudOff,
  FileText,
  Wrench,
  WifiOff,
  Key,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  X,
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { RetryButton } from "./retry-button";
import type { AppError, ErrorType, SuggestedAction } from "./types";

const ERROR_ICONS: Record<ErrorType, typeof AlertCircle> = {
  rate_limit: Clock,
  provider_down: CloudOff,
  context_overflow: FileText,
  tool_failed: Wrench,
  network: WifiOff,
  auth: Key,
  unknown: AlertCircle,
};

interface ErrorMessageProps {
  error: AppError;
  onRetry?: () => void;
  onSwitchModel?: () => void;
  onReduceContext?: () => void;
  onDismiss?: () => void;
  onCustomAction?: (actionId: string) => void;
  compact?: boolean;
  className?: string;
}

/**
 * ErrorMessage - Inline error display with actionable recovery options.
 *
 * Design: Warm, non-alarming colors. Amber for warnings, burgundy for errors.
 * Clear explanations with suggested next steps.
 */
export function ErrorMessage({
  error,
  onRetry,
  onSwitchModel,
  onReduceContext,
  onDismiss,
  onCustomAction,
  compact = false,
  className,
}: ErrorMessageProps) {
  const [showDetails, setShowDetails] = useState(false);
  const Icon = ERROR_ICONS[error.type] || AlertCircle;

  const isWarning = error.severity === "warning";
  const isCritical = error.severity === "critical";

  const handleAction = (action: SuggestedAction) => {
    switch (action.action) {
      case "retry":
        onRetry?.();
        break;
      case "switch_model":
        onSwitchModel?.();
        break;
      case "reduce_context":
        onReduceContext?.();
        break;
      case "dismiss":
        onDismiss?.();
        break;
      case "custom":
        onCustomAction?.(action.id);
        break;
    }
  };

  if (compact) {
    return (
      <div
        className={cn(
          "flex items-center gap-2 px-3 py-2 rounded-lg text-sm",
          isWarning
            ? "bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
            : "bg-rose-50 text-rose-800 dark:bg-rose-950/40 dark:text-rose-200",
          className
        )}
      >
        <Icon className="h-4 w-4 flex-shrink-0" />
        <span className="flex-1 min-w-0 truncate">{error.message}</span>
        {error.retryable && onRetry && (
          <button
            onClick={onRetry}
            className={cn(
              "text-xs font-medium px-2 py-0.5 rounded",
              isWarning
                ? "bg-amber-200/50 hover:bg-amber-200 dark:bg-amber-800/50 dark:hover:bg-amber-800"
                : "bg-rose-200/50 hover:bg-rose-200 dark:bg-rose-800/50 dark:hover:bg-rose-800"
            )}
          >
            Retry
          </button>
        )}
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="p-0.5 rounded hover:bg-current/10"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "rounded-xl border overflow-hidden",
        isWarning
          ? "bg-gradient-to-br from-amber-50 to-orange-50/50 border-amber-200 dark:from-amber-950/30 dark:to-orange-950/20 dark:border-amber-800/50"
          : isCritical
            ? "bg-gradient-to-br from-rose-50 to-red-50/50 border-rose-300 dark:from-rose-950/40 dark:to-red-950/30 dark:border-rose-700/50"
            : "bg-gradient-to-br from-rose-50 to-pink-50/50 border-rose-200 dark:from-rose-950/30 dark:to-pink-950/20 dark:border-rose-800/50",
        className
      )}
    >
      {/* Header */}
      <div className="px-4 py-3 flex items-start gap-3">
        <div
          className={cn(
            "p-2 rounded-lg",
            isWarning
              ? "bg-amber-100 dark:bg-amber-900/50"
              : "bg-rose-100 dark:bg-rose-900/50"
          )}
        >
          <Icon
            className={cn(
              "h-5 w-5",
              isWarning
                ? "text-amber-600 dark:text-amber-400"
                : "text-rose-600 dark:text-rose-400"
            )}
          />
        </div>

        <div className="flex-1 min-w-0">
          <h3
            className={cn(
              "font-semibold",
              isWarning
                ? "text-amber-900 dark:text-amber-100"
                : "text-rose-900 dark:text-rose-100"
            )}
          >
            {error.title}
          </h3>
          <p
            className={cn(
              "text-sm mt-0.5",
              isWarning
                ? "text-amber-700 dark:text-amber-300"
                : "text-rose-700 dark:text-rose-300"
            )}
          >
            {error.message}
          </p>

          {/* Details toggle */}
          {error.details && (
            <button
              onClick={() => setShowDetails(!showDetails)}
              className={cn(
                "flex items-center gap-1 text-xs mt-2 font-medium",
                isWarning
                  ? "text-amber-600 dark:text-amber-400"
                  : "text-rose-600 dark:text-rose-400"
              )}
            >
              {showDetails ? (
                <>
                  <ChevronUp className="h-3 w-3" /> Hide details
                </>
              ) : (
                <>
                  <ChevronDown className="h-3 w-3" /> Show details
                </>
              )}
            </button>
          )}
        </div>

        {/* Dismiss button */}
        {onDismiss && (
          <button
            onClick={onDismiss}
            className={cn(
              "p-1 rounded-md transition-colors",
              isWarning
                ? "text-amber-400 hover:text-amber-600 hover:bg-amber-100 dark:hover:bg-amber-900/50"
                : "text-rose-400 hover:text-rose-600 hover:bg-rose-100 dark:hover:bg-rose-900/50"
            )}
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Details */}
      {showDetails && error.details && (
        <div
          className={cn(
            "px-4 py-3 text-xs font-mono border-t",
            isWarning
              ? "bg-amber-100/50 border-amber-200 text-amber-800 dark:bg-amber-950/50 dark:border-amber-800/50 dark:text-amber-200"
              : "bg-rose-100/50 border-rose-200 text-rose-800 dark:bg-rose-950/50 dark:border-rose-800/50 dark:text-rose-200"
          )}
        >
          <pre className="whitespace-pre-wrap break-words">{error.details}</pre>
        </div>
      )}

      {/* Actions */}
      {error.suggestedActions && error.suggestedActions.length > 0 && (
        <div
          className={cn(
            "px-4 py-3 flex flex-wrap gap-2 border-t",
            isWarning
              ? "bg-amber-50/50 border-amber-200 dark:bg-amber-950/20 dark:border-amber-800/50"
              : "bg-rose-50/50 border-rose-200 dark:bg-rose-950/20 dark:border-rose-800/50"
          )}
        >
          {error.suggestedActions.map((action) => (
            <ActionButton
              key={action.id}
              action={action}
              onClick={() => handleAction(action)}
              variant={isWarning ? "warning" : "error"}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface ActionButtonProps {
  action: SuggestedAction;
  onClick: () => void;
  variant: "warning" | "error";
}

function ActionButton({ action, onClick, variant }: ActionButtonProps) {
  const isWarning = variant === "warning";

  if (action.action === "retry") {
    return (
      <RetryButton
        onClick={onClick}
        variant={variant}
        size={action.primary ? "md" : "sm"}
      />
    );
  }

  return (
    <button
      onClick={onClick}
      className={cn(
        "px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200",
        action.primary
          ? isWarning
            ? "bg-amber-600 text-white hover:bg-amber-700 dark:bg-amber-500 dark:hover:bg-amber-600"
            : "bg-rose-600 text-white hover:bg-rose-700 dark:bg-rose-500 dark:hover:bg-rose-600"
          : isWarning
            ? "bg-amber-100 text-amber-700 hover:bg-amber-200 dark:bg-amber-900/50 dark:text-amber-300 dark:hover:bg-amber-900"
            : "bg-rose-100 text-rose-700 hover:bg-rose-200 dark:bg-rose-900/50 dark:text-rose-300 dark:hover:bg-rose-900"
      )}
    >
      {action.label}
    </button>
  );
}
