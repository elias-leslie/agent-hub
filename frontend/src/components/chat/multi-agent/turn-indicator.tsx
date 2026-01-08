"use client";

import { cn } from "@/lib/utils";
import { AgentAvatar } from "./agent-badge";
import type { Agent, AgentTurnState, TurnState } from "./types";

interface TurnIndicatorProps {
  agents: Agent[];
  turnStates: AgentTurnState[];
  className?: string;
}

const TURN_LABELS: Record<TurnState, string> = {
  idle: "",
  thinking: "thinking...",
  responding: "responding",
  waiting: "waiting",
};

/**
 * TurnIndicator - Visual indicator showing which agent is currently active.
 *
 * Design: Horizontal strip with agent avatars, active agent is highlighted
 * with a pulsing indicator and state label.
 */
export function TurnIndicator({
  agents,
  turnStates,
  className,
}: TurnIndicatorProps) {
  const activeAgents = turnStates.filter((t) => t.state !== "idle");

  if (activeAgents.length === 0) {
    return null;
  }

  return (
    <div
      className={cn(
        "flex items-center gap-3 px-4 py-2 rounded-lg",
        "bg-slate-50 dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800",
        className
      )}
    >
      <div className="flex -space-x-2">
        {agents.map((agent) => {
          const turnState = turnStates.find((t) => t.agentId === agent.id);
          const isActive = turnState && turnState.state !== "idle";

          return (
            <div
              key={agent.id}
              className={cn(
                "transition-all duration-300",
                isActive ? "z-10 scale-110" : "opacity-40 grayscale"
              )}
            >
              <AgentAvatar agent={agent} size="sm" isActive={isActive} />
            </div>
          );
        })}
      </div>

      <div className="flex flex-col min-w-0">
        {activeAgents.map((turnState) => {
          const agent = agents.find((a) => a.id === turnState.agentId);
          if (!agent) return null;

          const isClaude = agent.provider === "claude";

          return (
            <div
              key={turnState.agentId}
              className="flex items-center gap-2 text-sm"
            >
              <span
                className={cn(
                  "font-medium",
                  isClaude
                    ? "text-orange-600 dark:text-orange-400"
                    : "text-blue-600 dark:text-blue-400"
                )}
              >
                {agent.shortName}
              </span>
              <span className="text-slate-500 dark:text-slate-400 text-xs">
                {TURN_LABELS[turnState.state]}
              </span>
              {turnState.state === "thinking" && (
                <ThinkingDots
                  className={
                    isClaude
                      ? "text-orange-500 dark:text-orange-400"
                      : "text-blue-500 dark:text-blue-400"
                  }
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface TurnIndicatorCompactProps {
  agent: Agent;
  state: TurnState;
  className?: string;
}

/**
 * TurnIndicatorCompact - Minimal inline indicator for single agent state.
 */
export function TurnIndicatorCompact({
  agent,
  state,
  className,
}: TurnIndicatorCompactProps) {
  if (state === "idle") return null;

  const isClaude = agent.provider === "claude";

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs",
        isClaude
          ? "bg-orange-50 text-orange-600 dark:bg-orange-950/50 dark:text-orange-400"
          : "bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-400",
        className
      )}
    >
      <span className="font-medium">{agent.shortName}</span>
      <span className="opacity-70">{TURN_LABELS[state]}</span>
      {state === "thinking" && (
        <ThinkingDots
          className={
            isClaude
              ? "text-orange-500 dark:text-orange-400"
              : "text-blue-500 dark:text-blue-400"
          }
        />
      )}
    </div>
  );
}

function ThinkingDots({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex gap-0.5", className)}>
      <span className="h-1 w-1 rounded-full bg-current animate-bounce [animation-delay:-0.3s]" />
      <span className="h-1 w-1 rounded-full bg-current animate-bounce [animation-delay:-0.15s]" />
      <span className="h-1 w-1 rounded-full bg-current animate-bounce" />
    </span>
  );
}
