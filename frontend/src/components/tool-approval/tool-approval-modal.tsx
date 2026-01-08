"use client";

import { useState, useEffect, useCallback } from "react";
import {
  ShieldCheck,
  AlertTriangle,
  AlertOctagon,
  X,
  Check,
  CheckCheck,
  Ban,
  XCircle,
  Clock,
  Terminal,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  ApprovalRequest,
  ApprovalDecision,
  RiskLevel,
  RISK_CONFIG,
} from "./types";

const RISK_ICONS: Record<RiskLevel, typeof ShieldCheck> = {
  low: ShieldCheck,
  medium: AlertTriangle,
  high: AlertOctagon,
};

interface ToolApprovalModalProps {
  request: ApprovalRequest;
  onDecision: (decision: ApprovalDecision, rememberChoice: boolean) => void;
  onClose?: () => void;
  queueLength?: number;
}

/**
 * ToolApprovalModal - Modal for approving/denying tool execution.
 *
 * Design: Industrial/utilitarian with clear risk indication.
 * Quick keyboard shortcuts for power users.
 */
export function ToolApprovalModal({
  request,
  onDecision,
  onClose,
  queueLength = 0,
}: ToolApprovalModalProps) {
  const [rememberChoice, setRememberChoice] = useState(false);
  const [timeRemaining, setTimeRemaining] = useState(request.timeoutSeconds);
  const [isExpanded, setIsExpanded] = useState(false);

  const { toolCall } = request;
  const RiskIcon = RISK_ICONS[toolCall.riskLevel];

  // Countdown timer
  useEffect(() => {
    if (timeRemaining <= 0) {
      onDecision("timeout", false);
      return;
    }

    const timer = setInterval(() => {
      setTimeRemaining((prev) => prev - 1);
    }, 1000);

    return () => clearInterval(timer);
  }, [timeRemaining, onDecision]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;

      switch (e.key.toLowerCase()) {
        case "y":
        case "enter":
          e.preventDefault();
          onDecision("approve", rememberChoice);
          break;
        case "a":
          if (e.shiftKey) {
            e.preventDefault();
            onDecision("approve_all", false);
          }
          break;
        case "n":
          e.preventDefault();
          onDecision("deny", rememberChoice);
          break;
        case "d":
          if (e.shiftKey) {
            e.preventDefault();
            onDecision("deny_all", false);
          }
          break;
        case "escape":
          onClose?.();
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onDecision, rememberChoice, onClose]);

  const handleDecision = useCallback(
    (decision: ApprovalDecision) => {
      onDecision(decision, rememberChoice);
    },
    [onDecision, rememberChoice]
  );

  const timeoutPercentage = (timeRemaining / request.timeoutSeconds) * 100;
  const isUrgent = timeRemaining <= 10;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-slate-900/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div
        className={cn(
          "relative w-full max-w-lg rounded-xl overflow-hidden shadow-2xl",
          "bg-white dark:bg-slate-900",
          "border-2",
          toolCall.riskLevel === "low" && "border-emerald-300 dark:border-emerald-700",
          toolCall.riskLevel === "medium" && "border-amber-300 dark:border-amber-700",
          toolCall.riskLevel === "high" && "border-rose-400 dark:border-rose-600",
          "animate-in zoom-in-95 fade-in duration-200"
        )}
      >
        {/* Timeout progress bar */}
        <div className="h-1 bg-slate-200 dark:bg-slate-800">
          <div
            className={cn(
              "h-full transition-all duration-1000 ease-linear",
              isUrgent
                ? "bg-rose-500 animate-pulse"
                : toolCall.riskLevel === "low"
                  ? "bg-emerald-500"
                  : toolCall.riskLevel === "medium"
                    ? "bg-amber-500"
                    : "bg-rose-500"
            )}
            style={{ width: `${timeoutPercentage}%` }}
          />
        </div>

        {/* Header */}
        <div
          className={cn(
            "px-5 py-4 flex items-start gap-4",
            toolCall.riskLevel === "low" && "bg-emerald-50 dark:bg-emerald-950/30",
            toolCall.riskLevel === "medium" && "bg-amber-50 dark:bg-amber-950/30",
            toolCall.riskLevel === "high" && "bg-rose-50 dark:bg-rose-950/30"
          )}
        >
          <div
            className={cn(
              "p-2.5 rounded-xl",
              toolCall.riskLevel === "low" && "bg-emerald-100 dark:bg-emerald-900/50",
              toolCall.riskLevel === "medium" && "bg-amber-100 dark:bg-amber-900/50",
              toolCall.riskLevel === "high" && "bg-rose-100 dark:bg-rose-900/50"
            )}
          >
            <RiskIcon
              className={cn(
                "h-6 w-6",
                toolCall.riskLevel === "low" && "text-emerald-600 dark:text-emerald-400",
                toolCall.riskLevel === "medium" && "text-amber-600 dark:text-amber-400",
                toolCall.riskLevel === "high" && "text-rose-600 dark:text-rose-400"
              )}
            />
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
                Tool Approval Required
              </h2>
              {queueLength > 0 && (
                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-400">
                  +{queueLength} more
                </span>
              )}
            </div>
            <p
              className={cn(
                "text-sm mt-0.5",
                toolCall.riskLevel === "low" && "text-emerald-700 dark:text-emerald-400",
                toolCall.riskLevel === "medium" && "text-amber-700 dark:text-amber-400",
                toolCall.riskLevel === "high" && "text-rose-700 dark:text-rose-400"
              )}
            >
              {toolCall.riskLevel === "low" && "Safe operation with minimal impact"}
              {toolCall.riskLevel === "medium" && "Review parameters before approving"}
              {toolCall.riskLevel === "high" && "Potentially destructive - review carefully"}
            </p>
          </div>

          {/* Timer */}
          <div
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-sm font-mono",
              isUrgent
                ? "bg-rose-100 text-rose-700 dark:bg-rose-900/50 dark:text-rose-400 animate-pulse"
                : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400"
            )}
          >
            <Clock className="h-4 w-4" />
            {timeRemaining}s
          </div>
        </div>

        {/* Content */}
        <div className="px-5 py-4 space-y-4">
          {/* Tool name */}
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800">
              <Terminal className="h-5 w-5 text-slate-500 dark:text-slate-400" />
            </div>
            <div>
              <p className="text-xs text-slate-500 dark:text-slate-400 uppercase tracking-wider font-medium">
                Tool
              </p>
              <p className="font-mono font-semibold text-slate-900 dark:text-slate-100">
                {toolCall.toolName}
              </p>
            </div>
          </div>

          {/* Agent info */}
          {request.agentName && (
            <div className="text-sm text-slate-500 dark:text-slate-400">
              Requested by: <span className="font-medium">{request.agentName}</span>
            </div>
          )}

          {/* Parameters */}
          <div>
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="flex items-center justify-between w-full text-left"
            >
              <p className="text-xs text-slate-500 dark:text-slate-400 uppercase tracking-wider font-medium">
                Parameters
              </p>
              <span className="text-xs text-slate-400 dark:text-slate-500">
                {isExpanded ? "Collapse" : "Expand"}
              </span>
            </button>
            <div
              className={cn(
                "mt-2 rounded-lg overflow-hidden transition-all",
                "bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700"
              )}
            >
              <pre
                className={cn(
                  "p-3 text-xs font-mono text-slate-700 dark:text-slate-300 overflow-x-auto",
                  !isExpanded && "max-h-24"
                )}
              >
                {JSON.stringify(toolCall.parameters, null, 2)}
              </pre>
            </div>
          </div>

          {/* Remember choice */}
          <label className="flex items-center gap-2 cursor-pointer group">
            <input
              type="checkbox"
              checked={rememberChoice}
              onChange={(e) => setRememberChoice(e.target.checked)}
              className={cn(
                "h-4 w-4 rounded border-slate-300 dark:border-slate-600",
                "text-blue-600 focus:ring-blue-500"
              )}
            />
            <span className="text-sm text-slate-600 dark:text-slate-400 group-hover:text-slate-900 dark:group-hover:text-slate-200">
              Remember this choice for <span className="font-mono">{toolCall.toolName}</span>
            </span>
          </label>
        </div>

        {/* Actions */}
        <div className="px-5 py-4 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-200 dark:border-slate-700">
          <div className="flex flex-wrap gap-2">
            {/* Approve */}
            <button
              onClick={() => handleDecision("approve")}
              className={cn(
                "flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg",
                "bg-emerald-600 text-white font-medium",
                "hover:bg-emerald-700 transition-colors",
                "focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2"
              )}
            >
              <Check className="h-4 w-4" />
              <span>Approve</span>
              <kbd className="ml-1 px-1.5 py-0.5 text-xs rounded bg-emerald-700/50">Y</kbd>
            </button>

            {/* Deny */}
            <button
              onClick={() => handleDecision("deny")}
              className={cn(
                "flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg",
                "bg-rose-600 text-white font-medium",
                "hover:bg-rose-700 transition-colors",
                "focus:outline-none focus:ring-2 focus:ring-rose-500 focus:ring-offset-2"
              )}
            >
              <Ban className="h-4 w-4" />
              <span>Deny</span>
              <kbd className="ml-1 px-1.5 py-0.5 text-xs rounded bg-rose-700/50">N</kbd>
            </button>
          </div>

          {/* Secondary actions */}
          <div className="flex gap-2 mt-2">
            <button
              onClick={() => handleDecision("approve_all")}
              className={cn(
                "flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm",
                "bg-amber-100 text-amber-700 font-medium",
                "hover:bg-amber-200 dark:bg-amber-900/40 dark:text-amber-400 dark:hover:bg-amber-900/60",
                "transition-colors"
              )}
            >
              <CheckCheck className="h-4 w-4" />
              <span>Approve All (YOLO)</span>
              <kbd className="ml-1 px-1 py-0.5 text-xs rounded bg-amber-200 dark:bg-amber-800">⇧A</kbd>
            </button>

            <button
              onClick={() => handleDecision("deny_all")}
              className={cn(
                "flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm",
                "bg-slate-200 text-slate-700 font-medium",
                "hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600",
                "transition-colors"
              )}
            >
              <XCircle className="h-4 w-4" />
              <span>Deny All</span>
              <kbd className="ml-1 px-1 py-0.5 text-xs rounded bg-slate-300 dark:bg-slate-600">⇧D</kbd>
            </button>
          </div>
        </div>

        {/* Close button */}
        {onClose && (
          <button
            onClick={onClose}
            className="absolute top-4 right-4 p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:text-slate-300 dark:hover:bg-slate-800 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        )}
      </div>
    </div>
  );
}
