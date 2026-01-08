"use client";

import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { AgentAvatar, AgentBadge } from "./agent-badge";
import type { Agent, AgentMessage } from "./types";

interface AgentExchangeProps {
  fromAgent: Agent;
  toAgent: Agent;
  message: AgentMessage;
  className?: string;
}

/**
 * AgentExchange - Styled component for agent-to-agent messages.
 *
 * Design: Distinct visual treatment with connecting line between
 * agent avatars, showing the flow of conversation between AI agents.
 */
export function AgentExchange({
  fromAgent,
  toAgent,
  message,
  className,
}: AgentExchangeProps) {
  const isClaude = fromAgent.provider === "claude";

  return (
    <div
      className={cn(
        "relative pl-4 py-3",
        "before:absolute before:left-0 before:top-0 before:bottom-0 before:w-0.5",
        isClaude
          ? "before:bg-gradient-to-b before:from-orange-300 before:to-orange-100 dark:before:from-orange-600 dark:before:to-orange-900"
          : "before:bg-gradient-to-b before:from-blue-300 before:to-blue-100 dark:before:from-blue-600 dark:before:to-blue-900",
        className
      )}
    >
      {/* Header: From -> To */}
      <div className="flex items-center gap-2 mb-2">
        <AgentAvatar agent={fromAgent} size="sm" />
        <ArrowRight className="h-3 w-3 text-slate-400 dark:text-slate-500" />
        <AgentAvatar agent={toAgent} size="sm" />
        <span className="text-xs text-slate-500 dark:text-slate-400 ml-1">
          {fromAgent.shortName} to {toAgent.shortName}
        </span>
      </div>

      {/* Message content */}
      <div
        className={cn(
          "ml-3 p-3 rounded-lg text-sm",
          "border border-dashed",
          isClaude
            ? "bg-orange-50/50 border-orange-200 text-slate-700 dark:bg-orange-950/20 dark:border-orange-800/50 dark:text-slate-300"
            : "bg-blue-50/50 border-blue-200 text-slate-700 dark:bg-blue-950/20 dark:border-blue-800/50 dark:text-slate-300"
        )}
      >
        <p className="whitespace-pre-wrap">{message.content}</p>
      </div>

      {/* Timestamp */}
      <div className="ml-3 mt-1.5 text-xs text-slate-400 dark:text-slate-500">
        {message.timestamp.toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        })}
      </div>
    </div>
  );
}

interface AgentMessageBubbleProps {
  agent: Agent;
  message: AgentMessage;
  isStreaming?: boolean;
  showAvatar?: boolean;
  className?: string;
}

/**
 * AgentMessageBubble - Single message with agent identity badge.
 */
export function AgentMessageBubble({
  agent,
  message,
  isStreaming = false,
  showAvatar = true,
  className,
}: AgentMessageBubbleProps) {
  const isClaude = agent.provider === "claude";

  return (
    <div className={cn("flex items-start gap-3", className)}>
      {showAvatar && (
        <AgentAvatar agent={agent} size="md" isActive={isStreaming} />
      )}

      <div className="flex-1 min-w-0">
        {/* Agent badge */}
        <div className="flex items-center gap-2 mb-1.5">
          <AgentBadge agent={agent} size="sm" />
          <span className="text-xs text-slate-400 dark:text-slate-500">
            {message.timestamp.toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
          {message.isDeliberation && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              deliberation
            </span>
          )}
          {message.isConsensus && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400 font-medium">
              consensus
            </span>
          )}
        </div>

        {/* Message content */}
        <div
          className={cn(
            "p-3 rounded-lg text-sm",
            isClaude
              ? "bg-gradient-to-br from-orange-50 to-amber-50/50 border border-orange-100 dark:from-orange-950/30 dark:to-amber-950/20 dark:border-orange-900/30"
              : "bg-gradient-to-br from-blue-50 to-indigo-50/50 border border-blue-100 dark:from-blue-950/30 dark:to-indigo-950/20 dark:border-blue-900/30"
          )}
        >
          <p className="whitespace-pre-wrap text-slate-700 dark:text-slate-300">
            {message.content}
            {isStreaming && (
              <span className="inline-block w-2 h-4 ml-1 bg-current animate-pulse" />
            )}
          </p>
        </div>
      </div>
    </div>
  );
}
