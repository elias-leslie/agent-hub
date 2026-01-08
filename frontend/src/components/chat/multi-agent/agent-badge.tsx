"use client";

import { Cpu, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Agent, AgentProvider } from "./types";

interface AgentBadgeProps {
  agent: Agent;
  size?: "sm" | "md" | "lg";
  showModel?: boolean;
  className?: string;
}

const PROVIDER_ICONS: Record<AgentProvider, typeof Cpu> = {
  claude: Cpu,
  gemini: Sparkles,
};

/**
 * AgentBadge - Shows agent identity with provider-specific color and icon.
 *
 * Design: Editorial/refined aesthetic with monospace model identifiers
 * and subtle color coding that's accessible in both light/dark modes.
 */
export function AgentBadge({
  agent,
  size = "md",
  showModel = false,
  className,
}: AgentBadgeProps) {
  const Icon = PROVIDER_ICONS[agent.provider];
  const isClaude = agent.provider === "claude";

  const sizeClasses = {
    sm: "px-1.5 py-0.5 text-xs gap-1",
    md: "px-2 py-1 text-sm gap-1.5",
    lg: "px-3 py-1.5 text-base gap-2",
  };

  const iconSizes = {
    sm: "h-3 w-3",
    md: "h-3.5 w-3.5",
    lg: "h-4 w-4",
  };

  return (
    <div
      className={cn(
        "inline-flex items-center rounded-md font-medium transition-all duration-200",
        sizeClasses[size],
        isClaude
          ? "bg-gradient-to-r from-orange-50 to-amber-50 text-orange-700 border border-orange-200/60 dark:from-orange-950/40 dark:to-amber-950/30 dark:text-orange-300 dark:border-orange-800/40"
          : "bg-gradient-to-r from-blue-50 to-indigo-50 text-blue-700 border border-blue-200/60 dark:from-blue-950/40 dark:to-indigo-950/30 dark:text-blue-300 dark:border-blue-800/40",
        className
      )}
    >
      <Icon
        className={cn(
          iconSizes[size],
          isClaude
            ? "text-orange-500 dark:text-orange-400"
            : "text-blue-500 dark:text-blue-400"
        )}
      />
      <span className="font-semibold tracking-tight">{agent.shortName}</span>
      {showModel && (
        <span
          className={cn(
            "font-mono text-[0.7em] opacity-60 ml-0.5",
            isClaude ? "text-orange-600 dark:text-orange-400" : "text-blue-600 dark:text-blue-400"
          )}
        >
          {agent.model.split("-").slice(-1)[0]}
        </span>
      )}
    </div>
  );
}

interface AgentAvatarProps {
  agent: Agent;
  size?: "sm" | "md" | "lg";
  isActive?: boolean;
  className?: string;
}

/**
 * AgentAvatar - Circular avatar with agent icon and pulsing active state.
 */
export function AgentAvatar({
  agent,
  size = "md",
  isActive = false,
  className,
}: AgentAvatarProps) {
  const Icon = PROVIDER_ICONS[agent.provider];
  const isClaude = agent.provider === "claude";

  const sizeClasses = {
    sm: "h-6 w-6",
    md: "h-8 w-8",
    lg: "h-10 w-10",
  };

  const iconSizes = {
    sm: "h-3 w-3",
    md: "h-4 w-4",
    lg: "h-5 w-5",
  };

  return (
    <div
      className={cn(
        "relative flex items-center justify-center rounded-full transition-all duration-300",
        sizeClasses[size],
        isClaude
          ? "bg-gradient-to-br from-orange-100 to-amber-100 dark:from-orange-900/50 dark:to-amber-900/40"
          : "bg-gradient-to-br from-blue-100 to-indigo-100 dark:from-blue-900/50 dark:to-indigo-900/40",
        isActive && "ring-2 ring-offset-2 ring-offset-background",
        isActive && isClaude && "ring-orange-400 dark:ring-orange-500",
        isActive && !isClaude && "ring-blue-400 dark:ring-blue-500",
        className
      )}
    >
      <Icon
        className={cn(
          iconSizes[size],
          isClaude
            ? "text-orange-600 dark:text-orange-400"
            : "text-blue-600 dark:text-blue-400"
        )}
      />
      {isActive && (
        <span
          className={cn(
            "absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full animate-pulse",
            isClaude ? "bg-orange-500" : "bg-blue-500"
          )}
        />
      )}
    </div>
  );
}
