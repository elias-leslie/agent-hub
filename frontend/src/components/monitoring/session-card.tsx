"use client";

import { Clock, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";
import { LiveBadge } from "./live-badge";

interface SessionCardProps {
  /** Session ID */
  id: string;
  /** Provider (claude or gemini) */
  provider: string;
  /** Model name */
  model: string;
  /** Session status */
  status: string;
  /** Number of messages */
  messageCount: number;
  /** Session creation time */
  createdAt: Date | string;
  /** Whether session is currently active */
  isLive?: boolean;
  /** Click handler */
  onClick?: () => void;
  /** Additional CSS classes */
  className?: string;
}

function formatRelativeTime(date: Date | string): string {
  const d = typeof date === "string" ? new Date(date) : date;
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}

function getModelShortName(model: string): string {
  // Extract version from model name (e.g., "claude-sonnet-4-5" -> "Sonnet 4.5")
  const lower = model.toLowerCase();
  if (lower.includes("sonnet")) {
    const vMatch = lower.match(/(\d)[.-](\d)/);
    return vMatch ? `Sonnet ${vMatch[1]}.${vMatch[2]}` : "Sonnet";
  }
  if (lower.includes("opus")) {
    const vMatch = lower.match(/(\d)[.-](\d)/);
    return vMatch ? `Opus ${vMatch[1]}.${vMatch[2]}` : "Opus";
  }
  if (lower.includes("haiku")) {
    const vMatch = lower.match(/(\d)[.-](\d)/);
    return vMatch ? `Haiku ${vMatch[1]}.${vMatch[2]}` : "Haiku";
  }
  if (lower.includes("gemini")) {
    if (lower.includes("flash")) return "Gemini Flash";
    if (lower.includes("pro")) return "Gemini Pro";
    return "Gemini";
  }
  return model.split("-").slice(0, 2).join(" ");
}

/**
 * SessionCard - Enhanced session card with live status indicator.
 *
 * Displays session metadata with optional live badge for active sessions.
 * Clickable for navigation to session detail.
 */
export function SessionCard({
  id,
  provider,
  model,
  status,
  messageCount,
  createdAt,
  isLive = false,
  onClick,
  className,
}: SessionCardProps) {
  const isClaude = provider.toLowerCase() === "claude";
  const modelShort = getModelShortName(model);

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full text-left p-4 rounded-lg border transition-all duration-200",
        "hover:shadow-md hover:border-primary/30",
        "focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
        isLive
          ? "border-green-200 bg-green-50/50 dark:border-green-800/50 dark:bg-green-950/20"
          : "border-border bg-card",
        className,
      )}
    >
      {/* Header row */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          {/* Provider badge */}
          <span
            className={cn(
              "px-2 py-0.5 rounded text-xs font-medium",
              isClaude
                ? "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300"
                : "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
            )}
          >
            {modelShort}
          </span>
          {isLive && <LiveBadge size="sm" />}
        </div>
        <span
          className={cn(
            "text-xs font-medium px-2 py-0.5 rounded",
            status === "active"
              ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300"
              : status === "completed"
                ? "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
                : "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300",
          )}
        >
          {status}
        </span>
      </div>

      {/* Session ID */}
      <p className="font-mono text-sm text-muted-foreground truncate mb-3">
        {id}
      </p>

      {/* Stats row */}
      <div className="flex items-center gap-4 text-xs text-muted-foreground">
        <div className="flex items-center gap-1">
          <MessageSquare className="h-3.5 w-3.5" />
          <span>{messageCount} messages</span>
        </div>
        <div className="flex items-center gap-1">
          <Clock className="h-3.5 w-3.5" />
          <span>{formatRelativeTime(createdAt)}</span>
        </div>
      </div>
    </button>
  );
}

interface SessionCardSkeletonProps {
  className?: string;
}

/**
 * SessionCardSkeleton - Loading state for SessionCard.
 */
export function SessionCardSkeleton({ className }: SessionCardSkeletonProps) {
  return (
    <div
      className={cn(
        "w-full p-4 rounded-lg border border-border bg-card animate-pulse",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="h-5 w-20 bg-muted rounded" />
        <div className="h-5 w-14 bg-muted rounded" />
      </div>
      <div className="h-4 w-48 bg-muted rounded mb-3" />
      <div className="flex items-center gap-4">
        <div className="h-3.5 w-24 bg-muted rounded" />
        <div className="h-3.5 w-16 bg-muted rounded" />
      </div>
    </div>
  );
}
