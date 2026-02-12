"use client";

import { useState, useCallback } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ApprovalRequest, ApprovalDecision } from "./types";
import { useApprovalTimer } from "./use-approval-timer";
import { useKeyboardShortcuts } from "./use-keyboard-shortcuts";
import { ModalHeader } from "./modal-header";
import { ModalContent } from "./modal-content";
import { ModalActions } from "./modal-actions";

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

  const { toolCall } = request;

  const handleTimeout = useCallback(
    (decision: ApprovalDecision) => {
      onDecision(decision, false);
    },
    [onDecision],
  );

  const { timeRemaining, timeoutPercentage, isUrgent } = useApprovalTimer({
    timeoutSeconds: request.timeoutSeconds,
    onTimeout: handleTimeout,
  });

  const handleDecision = useCallback(
    (decision: ApprovalDecision) => {
      onDecision(decision, rememberChoice);
    },
    [onDecision, rememberChoice],
  );

  useKeyboardShortcuts({
    onDecision,
    rememberChoice,
    onClose,
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-slate-900/60 backdrop-blur-sm"
        onClick={onClose}
      />

      <div
        data-testid="tool-approval-modal"
        className={cn(
          "relative w-full max-w-lg rounded-xl overflow-hidden shadow-2xl",
          "bg-white dark:bg-slate-900",
          "border-2",
          toolCall.riskLevel === "low" &&
            "border-emerald-300 dark:border-emerald-700",
          toolCall.riskLevel === "medium" &&
            "border-amber-300 dark:border-amber-700",
          toolCall.riskLevel === "high" &&
            "border-rose-400 dark:border-rose-600",
          "animate-in zoom-in-95 fade-in duration-200",
        )}
      >
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
                    : "bg-rose-500",
            )}
            style={{ width: `${timeoutPercentage}%` }}
          />
        </div>

        <ModalHeader
          toolCall={toolCall}
          queueLength={queueLength}
          timeRemaining={timeRemaining}
          isUrgent={isUrgent}
        />

        <ModalContent
          toolCall={toolCall}
          agentName={request.agentName}
          rememberChoice={rememberChoice}
          onRememberChoiceChange={setRememberChoice}
        />

        <ModalActions onDecision={handleDecision} />

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
