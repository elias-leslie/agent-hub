"use client";

import { useState } from "react";
import { Gauge, ChevronDown, ChevronUp, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

interface TruncationIndicatorProps {
  outputTokens?: number;
  maxTokensRequested?: number;
  modelLimit?: number;
  truncationWarning?: string;
}

/**
 * Visual truncation indicator with precision gauge aesthetic.
 * Shows token usage as a gauge meter with expandable details.
 */
export function TruncationIndicator({
  outputTokens,
  maxTokensRequested,
  modelLimit,
  truncationWarning,
}: TruncationIndicatorProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Calculate fill percentage for the gauge
  const usagePercent =
    maxTokensRequested && outputTokens
      ? Math.min((outputTokens / maxTokensRequested) * 100, 100)
      : 100;

  const limitPercent =
    modelLimit && maxTokensRequested
      ? Math.min((maxTokensRequested / modelLimit) * 100, 100)
      : 100;

  const formatNumber = (n?: number) => n?.toLocaleString() ?? "—";

  return (
    <div className="mt-3 group">
      {/* Main indicator bar */}
      <button
        data-truncation-indicator
        onClick={() => setIsExpanded(!isExpanded)}
        className={cn(
          "w-full flex items-center gap-2 px-3 py-2 rounded-lg transition-all duration-200",
          "bg-gradient-to-r from-amber-50/80 via-orange-50/60 to-amber-50/80",
          "dark:from-amber-950/40 dark:via-orange-950/30 dark:to-amber-950/40",
          "border border-amber-200/60 dark:border-amber-800/40",
          "hover:border-amber-300 dark:hover:border-amber-700",
          "hover:shadow-sm hover:shadow-amber-100 dark:hover:shadow-amber-950/50",
        )}
      >
        {/* Gauge icon with pulse animation */}
        <div className="relative">
          <Gauge className="h-4 w-4 text-amber-600 dark:text-amber-400" />
          <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
        </div>

        {/* Visual gauge meter */}
        <div className="flex-1 flex items-center gap-2">
          <div className="flex-1 h-2 bg-amber-100 dark:bg-amber-900/50 rounded-full overflow-hidden relative">
            {/* Model limit indicator (subtle background line) */}
            {limitPercent < 100 && (
              <div
                className="absolute h-full w-0.5 bg-amber-400/30 dark:bg-amber-500/20 z-10"
                style={{ left: `${limitPercent}%` }}
              />
            )}
            {/* Usage fill */}
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500 ease-out",
                "bg-gradient-to-r from-amber-400 via-orange-400 to-red-400",
                "dark:from-amber-500 dark:via-orange-500 dark:to-red-500",
              )}
              style={{ width: `${usagePercent}%` }}
            />
          </div>

          {/* Token count badge */}
          <span className="text-xs font-mono font-semibold text-amber-700 dark:text-amber-300 tabular-nums whitespace-nowrap">
            {formatNumber(outputTokens)}/{formatNumber(maxTokensRequested)}
          </span>
        </div>

        {/* Truncated label */}
        <div className="flex items-center gap-1 px-2 py-0.5 rounded bg-amber-200/50 dark:bg-amber-800/30">
          <AlertTriangle className="h-3 w-3 text-amber-600 dark:text-amber-400" />
          <span className="text-[10px] font-bold uppercase tracking-wider text-amber-700 dark:text-amber-300">
            Truncated
          </span>
        </div>

        {/* Expand/collapse chevron */}
        <div className="text-amber-500 dark:text-amber-400">
          {isExpanded ? (
            <ChevronUp className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </div>
      </button>

      {/* Expanded details panel */}
      {isExpanded && (
        <div
          className={cn(
            "mt-1 px-3 py-2.5 rounded-lg text-xs",
            "bg-amber-50/50 dark:bg-amber-950/20",
            "border border-amber-100 dark:border-amber-900/30",
            "animate-in slide-in-from-top-1 duration-200",
          )}
        >
          {/* Stats grid */}
          <div className="grid grid-cols-3 gap-3 mb-2">
            <div className="space-y-0.5">
              <div className="text-amber-500 dark:text-amber-500 font-medium uppercase tracking-wide text-[9px]">
                Output
              </div>
              <div className="font-mono font-bold text-amber-800 dark:text-amber-200 tabular-nums">
                {formatNumber(outputTokens)}
              </div>
            </div>
            <div className="space-y-0.5">
              <div className="text-amber-500 dark:text-amber-500 font-medium uppercase tracking-wide text-[9px]">
                Requested
              </div>
              <div className="font-mono font-bold text-amber-800 dark:text-amber-200 tabular-nums">
                {formatNumber(maxTokensRequested)}
              </div>
            </div>
            <div className="space-y-0.5">
              <div className="text-amber-500 dark:text-amber-500 font-medium uppercase tracking-wide text-[9px]">
                Model Max
              </div>
              <div className="font-mono font-bold text-amber-800 dark:text-amber-200 tabular-nums">
                {formatNumber(modelLimit)}
              </div>
            </div>
          </div>

          {/* Warning message */}
          {truncationWarning && (
            <div className="pt-2 border-t border-amber-200/50 dark:border-amber-800/30">
              <p className="text-amber-700 dark:text-amber-300 leading-relaxed">
                {truncationWarning}
              </p>
            </div>
          )}

          {/* Tip */}
          <div className="mt-2 pt-2 border-t border-amber-200/50 dark:border-amber-800/30 flex items-start gap-1.5">
            <span className="text-amber-400 dark:text-amber-600 text-[10px]">
              TIP
            </span>
            <p className="text-amber-600/80 dark:text-amber-400/70 text-[10px] leading-relaxed">
              Increase{" "}
              <code className="px-1 py-0.5 rounded bg-amber-200/50 dark:bg-amber-800/30 font-mono">
                max_tokens
              </code>{" "}
              in your request to get longer responses.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
