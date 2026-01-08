"use client";

import { useState } from "react";
import {
  ShieldCheck,
  AlertTriangle,
  AlertOctagon,
  ChevronRight,
  Terminal,
  Clock,
  Bell,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ApprovalRequest, RiskLevel } from "./types";

const RISK_ICONS: Record<RiskLevel, typeof ShieldCheck> = {
  low: ShieldCheck,
  medium: AlertTriangle,
  high: AlertOctagon,
};

interface ApprovalQueueProps {
  requests: ApprovalRequest[];
  onSelect: (request: ApprovalRequest) => void;
  className?: string;
}

/**
 * ApprovalQueue - List of pending tool approval requests.
 *
 * Design: Compact list with risk indicators and timing info.
 */
export function ApprovalQueue({
  requests,
  onSelect,
  className,
}: ApprovalQueueProps) {
  if (requests.length === 0) {
    return null;
  }

  // Sort by risk level (high first) and then by timestamp
  const sortedRequests = [...requests].sort((a, b) => {
    const riskOrder = { high: 0, medium: 1, low: 2 };
    const riskDiff = riskOrder[a.toolCall.riskLevel] - riskOrder[b.toolCall.riskLevel];
    if (riskDiff !== 0) return riskDiff;
    return a.toolCall.timestamp.getTime() - b.toolCall.timestamp.getTime();
  });

  return (
    <div
      className={cn(
        "rounded-xl border bg-white dark:bg-slate-900",
        "border-slate-200 dark:border-slate-800",
        className
      )}
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell className="h-4 w-4 text-amber-500" />
          <h3 className="font-semibold text-slate-900 dark:text-slate-100">
            Pending Approvals
          </h3>
        </div>
        <span
          className={cn(
            "px-2 py-0.5 text-sm font-medium rounded-full",
            requests.some((r) => r.toolCall.riskLevel === "high")
              ? "bg-rose-100 text-rose-700 dark:bg-rose-900/50 dark:text-rose-400"
              : requests.some((r) => r.toolCall.riskLevel === "medium")
                ? "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400"
                : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-400"
          )}
        >
          {requests.length}
        </span>
      </div>

      {/* Request list */}
      <div className="divide-y divide-slate-100 dark:divide-slate-800">
        {sortedRequests.map((request) => (
          <ApprovalQueueItem
            key={request.id}
            request={request}
            onClick={() => onSelect(request)}
          />
        ))}
      </div>
    </div>
  );
}

interface ApprovalQueueItemProps {
  request: ApprovalRequest;
  onClick: () => void;
}

function ApprovalQueueItem({ request, onClick }: ApprovalQueueItemProps) {
  const { toolCall } = request;
  const RiskIcon = RISK_ICONS[toolCall.riskLevel];

  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full flex items-center gap-3 px-4 py-3 text-left transition-colors",
        "hover:bg-slate-50 dark:hover:bg-slate-800/50"
      )}
    >
      {/* Risk indicator */}
      <div
        className={cn(
          "p-1.5 rounded-lg flex-shrink-0",
          toolCall.riskLevel === "low" && "bg-emerald-100 dark:bg-emerald-900/30",
          toolCall.riskLevel === "medium" && "bg-amber-100 dark:bg-amber-900/30",
          toolCall.riskLevel === "high" && "bg-rose-100 dark:bg-rose-900/30"
        )}
      >
        <RiskIcon
          className={cn(
            "h-4 w-4",
            toolCall.riskLevel === "low" && "text-emerald-600 dark:text-emerald-400",
            toolCall.riskLevel === "medium" && "text-amber-600 dark:text-amber-400",
            toolCall.riskLevel === "high" && "text-rose-600 dark:text-rose-400"
          )}
        />
      </div>

      {/* Tool info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <Terminal className="h-3.5 w-3.5 text-slate-400" />
          <span className="font-mono text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
            {toolCall.toolName}
          </span>
        </div>
        {request.agentName && (
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            {request.agentName}
          </p>
        )}
      </div>

      {/* Timeout */}
      <div className="flex items-center gap-1 text-xs text-slate-400 dark:text-slate-500">
        <Clock className="h-3.5 w-3.5" />
        {request.timeoutSeconds}s
      </div>

      <ChevronRight className="h-4 w-4 text-slate-300 dark:text-slate-600" />
    </button>
  );
}

interface ApprovalBadgeProps {
  count: number;
  hasHighRisk?: boolean;
  onClick?: () => void;
  className?: string;
}

/**
 * ApprovalBadge - Compact badge showing pending approval count.
 */
export function ApprovalBadge({
  count,
  hasHighRisk = false,
  onClick,
  className,
}: ApprovalBadgeProps) {
  if (count === 0) return null;

  return (
    <button
      onClick={onClick}
      className={cn(
        "relative inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-sm font-medium",
        "transition-all duration-200",
        hasHighRisk
          ? "bg-rose-100 text-rose-700 hover:bg-rose-200 dark:bg-rose-900/50 dark:text-rose-400 dark:hover:bg-rose-900/70"
          : "bg-amber-100 text-amber-700 hover:bg-amber-200 dark:bg-amber-900/50 dark:text-amber-400 dark:hover:bg-amber-900/70",
        className
      )}
    >
      <Bell className={cn("h-4 w-4", hasHighRisk && "animate-bounce")} />
      <span>{count} pending</span>
      {hasHighRisk && (
        <span className="absolute -top-1 -right-1 h-3 w-3 rounded-full bg-rose-500 animate-pulse" />
      )}
    </button>
  );
}

interface RiskIndicatorProps {
  level: RiskLevel;
  showLabel?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
}

/**
 * RiskIndicator - Visual risk level indicator.
 */
export function RiskIndicator({
  level,
  showLabel = true,
  size = "md",
  className,
}: RiskIndicatorProps) {
  const Icon = RISK_ICONS[level];

  const sizeClasses = {
    sm: "px-1.5 py-0.5 text-xs gap-1",
    md: "px-2 py-1 text-sm gap-1.5",
    lg: "px-3 py-1.5 text-base gap-2",
  };

  const iconSizes = {
    sm: "h-3 w-3",
    md: "h-4 w-4",
    lg: "h-5 w-5",
  };

  const labels: Record<RiskLevel, string> = {
    low: "Low",
    medium: "Medium",
    high: "High",
  };

  return (
    <div
      className={cn(
        "inline-flex items-center rounded-md font-medium",
        sizeClasses[size],
        level === "low" && "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-400",
        level === "medium" && "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400",
        level === "high" && "bg-rose-100 text-rose-700 dark:bg-rose-900/50 dark:text-rose-400",
        className
      )}
    >
      <Icon className={iconSizes[size]} />
      {showLabel && <span>{labels[level]}</span>}
    </div>
  );
}
