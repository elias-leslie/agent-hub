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
import { cn } from "@/lib/utils";

export type ActivityState =
  | "idle"
  | "connecting"
  | "thinking"
  | "calling_tool"
  | "streaming"
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
    color: "text-emerald-600 dark:text-emerald-400",
    bgColor: "bg-emerald-100 dark:bg-emerald-900/30",
  },
  connecting: {
    icon: Loader2,
    label: "Connecting...",
    color: "text-slate-600 dark:text-slate-400",
    bgColor: "bg-slate-100 dark:bg-slate-800",
    animate: true,
  },
  thinking: {
    icon: Brain,
    label: "Thinking...",
    color: "text-purple-600 dark:text-purple-400",
    bgColor: "bg-purple-100 dark:bg-purple-900/30",
    animate: true,
  },
  calling_tool: {
    icon: Wrench,
    label: "Calling tool...",
    color: "text-blue-600 dark:text-blue-400",
    bgColor: "bg-blue-100 dark:bg-blue-900/30",
    animate: true,
  },
  streaming: {
    icon: Bot,
    label: "Responding...",
    color: "text-blue-600 dark:text-blue-400",
    bgColor: "bg-blue-100 dark:bg-blue-900/30",
    animate: true,
  },
  cancelling: {
    icon: Loader2,
    label: "Cancelling...",
    color: "text-amber-600 dark:text-amber-400",
    bgColor: "bg-amber-100 dark:bg-amber-900/30",
    animate: true,
  },
  error: {
    icon: AlertCircle,
    label: "Error",
    color: "text-red-600 dark:text-red-400",
    bgColor: "bg-red-100 dark:bg-red-900/30",
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
  className,
}: ActivityIndicatorProps) {
  const [thinkingExpanded, setThinkingExpanded] = useState(false);
  const config = stateConfig[state];
  const Icon = config.icon;

  const displayLabel = toolCall?.name
    ? `Calling ${toolCall.name}...`
    : stepProgress
      ? `${config.label} (${stepProgress.current}/${stepProgress.total})`
      : config.label;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {/* Main indicator */}
      <div
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
          <div className="w-16 h-1.5 bg-white/50 dark:bg-slate-700 rounded-full overflow-hidden ml-1">
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
        <div className="rounded-lg border border-purple-200 dark:border-purple-800 bg-purple-50 dark:bg-purple-900/20 overflow-hidden">
          <button
            onClick={() => setThinkingExpanded(!thinkingExpanded)}
            className="w-full flex items-center justify-between px-3 py-2 text-sm text-purple-700 dark:text-purple-300 hover:bg-purple-100 dark:hover:bg-purple-900/30"
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
            <div className="px-3 py-2 border-t border-purple-200 dark:border-purple-800">
              <pre className="text-xs text-purple-600 dark:text-purple-400 whitespace-pre-wrap font-mono max-h-40 overflow-y-auto">
                {thinkingContent.content}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Tool call indicator */}
      {toolCall && state === "calling_tool" && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 text-sm">
          <Wrench
            className={cn(
              "h-4 w-4 text-blue-600 dark:text-blue-400",
              toolCall.status === "running" && "animate-pulse"
            )}
          />
          <span className="text-blue-700 dark:text-blue-300">
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
