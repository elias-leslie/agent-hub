"use client";

import { useState } from "react";
import {
  Loader2,
  Bot,
  Wrench,
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Brain,
} from "lucide-react";
import { cn } from "../lib/utils";

export type ActivityState =
  | "idle"
  | "connecting"
  | "waiting"
  | "working"
  | "retrying"
  | "thinking"
  | "calling_tool"
  | "streaming"
  | "reconnecting"
  | "cancelling"
  | "error";

export interface ToolCall {
  name: string;
  status: "running" | "complete" | "error";
}

export interface ThinkingContent {
  content: string;
  timestamp: Date;
}

export interface ActivityIndicatorProps {
  state: ActivityState;
  toolCall?: ToolCall;
  thinkingContent?: ThinkingContent;
  stepProgress?: { current: number; total: number };
  /** Replaces the state's wording, e.g. to name the tool being called. */
  label?: string;
  /** The host announces the status to screen readers elsewhere (a live region); hide the pill from them. */
  decorative?: boolean;
  className?: string;
}

const stateConfig: Record<
  ActivityState,
  {
    icon: typeof Bot;
    label: string;
    color: string;
    bgColor: string;
    animate?: boolean;
  }
> = {
  idle: {
    icon: CheckCircle,
    label: "Ready",
    color: "text-emerald-400",
    bgColor: "bg-emerald-900/30",
  },
  connecting: {
    icon: Loader2,
    label: "Connecting...",
    color: "text-muted-foreground",
    bgColor: "bg-muted",
    animate: true,
  },
  waiting: {
    icon: Loader2,
    label: "Waiting for the model...",
    color: "text-muted-foreground",
    bgColor: "bg-muted",
    animate: true,
  },
  working: {
    icon: Loader2,
    label: "Working...",
    color: "text-muted-foreground",
    bgColor: "bg-muted",
    animate: true,
  },
  retrying: {
    icon: Loader2,
    label: "Retrying...",
    color: "text-amber-400",
    bgColor: "bg-amber-900/30",
    animate: true,
  },
  thinking: {
    icon: Brain,
    label: "Thinking...",
    color: "text-purple-400",
    bgColor: "bg-purple-900/30",
    animate: true,
  },
  calling_tool: {
    icon: Wrench,
    label: "Calling tool...",
    color: "text-blue-400",
    bgColor: "bg-blue-900/30",
    animate: true,
  },
  streaming: {
    icon: Bot,
    label: "Responding...",
    color: "text-blue-400",
    bgColor: "bg-blue-900/30",
    animate: true,
  },
  reconnecting: {
    icon: Loader2,
    label: "Reconnecting...",
    color: "text-amber-400",
    bgColor: "bg-amber-900/30",
    animate: true,
  },
  cancelling: {
    icon: Loader2,
    label: "Cancelling...",
    color: "text-amber-400",
    bgColor: "bg-amber-900/30",
    animate: true,
  },
  error: {
    icon: AlertCircle,
    label: "Error",
    color: "text-red-400",
    bgColor: "bg-red-900/30",
  },
};

/**
 * ActivityIndicator shows the current state of the AI agent.
 * Supports extended states including tool calls and thinking content.
 */
export function ActivityIndicator({
  state,
  toolCall,
  thinkingContent,
  stepProgress,
  label,
  decorative,
  className,
}: ActivityIndicatorProps) {
  const [thinkingExpanded, setThinkingExpanded] = useState(false);
  const config = stateConfig[state];
  const Icon = config.icon;

  const baseLabel = label ?? config.label;
  const displayLabel = toolCall?.name
    ? `Calling ${toolCall.name}...`
    : stepProgress
      ? `${baseLabel} (${stepProgress.current}/${stepProgress.total})`
      : baseLabel;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {/* Main indicator */}
      <div
        data-testid="activity-pill"
        data-state={state}
        aria-hidden={decorative ? true : undefined}
        className={cn(
          "inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium",
          config.bgColor,
          config.color
        )}
      >
        <Icon
          className={cn("h-4 w-4", config.animate && "animate-spin")}
          style={
            state === "thinking" && config.animate
              ? { animation: "pulse 1.5s ease-in-out infinite" }
              : undefined
          }
        />
        <span>{displayLabel}</span>

        {/* Step progress bar */}
        {stepProgress && (
          <div className="w-16 h-1.5 bg-background/70 rounded-full overflow-hidden ml-1">
            <div
              className="h-full bg-current rounded-full transition-all duration-300"
              style={{
                width: `${(stepProgress.current / stepProgress.total) * 100}%`,
              }}
            />
          </div>
        )}
      </div>

      {/* Thinking content (expandable) */}
      {thinkingContent && state === "thinking" && (
        <div className="rounded-lg border border-purple-800 bg-purple-900/20 overflow-hidden">
          <button
            onClick={() => setThinkingExpanded(!thinkingExpanded)}
            className="w-full flex items-center justify-between px-3 py-2 text-sm text-purple-300 hover:bg-purple-900/30"
          >
            <span className="flex items-center gap-2">
              <Brain className="h-4 w-4" />
              Extended Thinking
            </span>
            {thinkingExpanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>

          {thinkingExpanded && (
            <div className="px-3 py-2 border-t border-purple-800">
              <pre className="text-xs text-purple-400 whitespace-pre-wrap font-mono max-h-40 overflow-y-auto">
                {thinkingContent.content}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Tool call indicator */}
      {toolCall && state === "calling_tool" && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-blue-800 bg-blue-900/20 text-sm">
          <Wrench
            className={cn(
              "h-4 w-4 text-blue-400",
              toolCall.status === "running" && "animate-pulse"
            )}
          />
          <span className="text-blue-300">
            {toolCall.name}
          </span>
          {toolCall.status === "complete" && (
            <CheckCircle className="h-4 w-4 text-emerald-500 ml-auto" />
          )}
          {toolCall.status === "error" && (
            <AlertCircle className="h-4 w-4 text-red-500 ml-auto" />
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Compact version for inline use in message list.
 */
export function ActivityIndicatorInline({
  state,
  className,
}: {
  state: ActivityState;
  className?: string;
}) {
  const config = stateConfig[state];
  const Icon = config.icon;

  return (
    <span
      className={cn("inline-flex items-center gap-1.5 text-xs", config.color, className)}
    >
      <Icon className={cn("h-3 w-3", config.animate && "animate-spin")} />
      <span>{config.label}</span>
    </span>
  );
}
