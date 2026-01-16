"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, MessageSquare, Award } from "lucide-react";
import { cn } from "@/lib/utils";
import { AgentMessageBubble } from "./agent-exchange";
import { AgentAvatar } from "./agent-badge";
import type { Agent, AgentExchangeThread } from "./types";

interface DeliberationPanelProps {
  thread: AgentExchangeThread;
  agents: Agent[];
  defaultExpanded?: boolean;
  className?: string;
}

/**
 * DeliberationPanel - Collapsible panel showing agent deliberation vs final consensus.
 *
 * Design: Elegant collapsible panel with visual separation between
 * the internal agent discussion and the final synthesized response.
 */
export function DeliberationPanel({
  thread,
  agents,
  defaultExpanded = false,
  className,
}: DeliberationPanelProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  const deliberationMessages = thread.messages.filter((m) => m.isDeliberation);
  const hasConsensus = !!thread.consensusMessage;

  // Get agents involved in this thread
  const involvedAgentIds = new Set(thread.messages.map((m) => m.agentId));
  const involvedAgents = agents.filter((a) => involvedAgentIds.has(a.id));

  const getAgentById = (id: string) => agents.find((a) => a.id === id);

  return (
    <div
      className={cn(
        "rounded-xl border overflow-hidden",
        "bg-slate-50/50 border-slate-200 dark:bg-slate-900/30 dark:border-slate-800",
        className,
      )}
    >
      {/* Header - always visible */}
      <button
        type="button"
        data-testid="deliberation-toggle"
        onClick={() => setIsExpanded(!isExpanded)}
        className={cn(
          "w-full flex items-center gap-3 px-4 py-3 text-left",
          "hover:bg-slate-100/50 dark:hover:bg-slate-800/30 transition-colors",
        )}
      >
        {/* Expand/collapse icon */}
        {isExpanded ? (
          <ChevronDown className="h-4 w-4 text-slate-400" />
        ) : (
          <ChevronRight className="h-4 w-4 text-slate-400" />
        )}

        {/* Involved agents avatars */}
        <div className="flex -space-x-1.5">
          {involvedAgents.map((agent) => (
            <AgentAvatar key={agent.id} agent={agent} size="sm" />
          ))}
        </div>

        {/* Label */}
        <div className="flex-1 min-w-0">
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
            Agent Discussion
          </span>
          <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">
            {deliberationMessages.length} message
            {deliberationMessages.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* Status badge */}
        {hasConsensus ? (
          <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400">
            <Award className="h-3 w-3" />
            Consensus reached
          </span>
        ) : (
          <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-amber-50 text-amber-600 dark:bg-amber-950/50 dark:text-amber-400">
            <MessageSquare className="h-3 w-3" />
            Deliberating
          </span>
        )}
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="border-t border-slate-200 dark:border-slate-800">
          {/* Deliberation messages */}
          <div className="p-4 space-y-4 bg-slate-100/30 dark:bg-slate-900/50">
            <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 mb-2">
              <MessageSquare className="h-3 w-3" />
              <span className="font-medium uppercase tracking-wider">
                Deliberation
              </span>
            </div>

            {deliberationMessages.map((message) => {
              const agent = getAgentById(message.agentId);
              if (!agent) return null;

              return (
                <AgentMessageBubble
                  key={message.id}
                  agent={agent}
                  message={message}
                />
              );
            })}
          </div>

          {/* Consensus message */}
          {hasConsensus && thread.consensusMessage && (
            <div className="p-4 bg-emerald-50/30 dark:bg-emerald-950/10">
              <div className="flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-400 mb-3">
                <Award className="h-3 w-3" />
                <span className="font-medium uppercase tracking-wider">
                  Final Consensus
                </span>
              </div>

              {(() => {
                const agent = getAgentById(thread.consensusMessage!.agentId);
                if (!agent) return null;
                return (
                  <AgentMessageBubble
                    agent={agent}
                    message={thread.consensusMessage!}
                  />
                );
              })()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface DeliberationSummaryProps {
  threads: AgentExchangeThread[];
  agents: Agent[];
  className?: string;
}

/**
 * DeliberationSummary - Overview of multiple deliberation threads.
 */
export function DeliberationSummary({
  threads,
  agents,
  className,
}: DeliberationSummaryProps) {
  const totalMessages = threads.reduce((sum, t) => sum + t.messages.length, 0);
  const consensusCount = threads.filter((t) => t.consensusMessage).length;

  return (
    <div
      className={cn(
        "flex items-center gap-4 px-4 py-2 rounded-lg",
        "bg-slate-100 dark:bg-slate-800 text-sm",
        className,
      )}
    >
      <div className="flex -space-x-1.5">
        {agents.slice(0, 3).map((agent) => (
          <AgentAvatar key={agent.id} agent={agent} size="sm" />
        ))}
        {agents.length > 3 && (
          <div className="h-6 w-6 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center text-xs text-slate-600 dark:text-slate-400">
            +{agents.length - 3}
          </div>
        )}
      </div>

      <div className="flex-1 min-w-0">
        <span className="text-slate-700 dark:text-slate-300">
          {threads.length} discussion{threads.length !== 1 ? "s" : ""}
        </span>
        <span className="mx-1.5 text-slate-400">|</span>
        <span className="text-slate-500 dark:text-slate-400">
          {totalMessages} total messages
        </span>
      </div>

      <div className="text-xs">
        <span className="text-emerald-600 dark:text-emerald-400">
          {consensusCount} consensus
        </span>
        {threads.length - consensusCount > 0 && (
          <span className="text-amber-600 dark:text-amber-400 ml-2">
            {threads.length - consensusCount} pending
          </span>
        )}
      </div>
    </div>
  );
}
