"use client";

import { useEffect, useRef } from "react";
import { User, Cpu, Sparkles, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { RoundtableMessage } from "@/hooks/use-roundtable";
import { AgentAvatar } from "./agent-badge";
import type { Agent } from "./types";

interface RoundtableTimelineProps {
  messages: RoundtableMessage[];
  className?: string;
}

// Default agent configurations
const CLAUDE_AGENT: Agent = {
  id: "claude",
  name: "Claude",
  shortName: "Claude",
  provider: "claude",
  model: "claude-sonnet-4-5",
};

const GEMINI_AGENT: Agent = {
  id: "gemini",
  name: "Gemini",
  shortName: "Gemini",
  provider: "gemini",
  model: "gemini-3-flash-preview",
};

/**
 * RoundtableTimeline - Unified timeline view of roundtable messages.
 *
 * Design decisions (per task decisions):
 * - d5: Unified timeline with interleaved messages
 * - d5: Color-coded agent badges (Claude: orange, Gemini: blue)
 * - Single column layout, not split panels
 * - Streaming indicator per agent
 */
export function RoundtableTimeline({
  messages,
  className,
}: RoundtableTimelineProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div
        className={cn(
          "flex-1 flex items-center justify-center text-muted-foreground",
          className
        )}
      >
        <p className="text-sm">Start a discussion by sending a message below.</p>
      </div>
    );
  }

  return (
    <div className={cn("flex-1 overflow-y-auto px-4 py-6 space-y-4", className)}>
      {messages.map((message) => (
        <TimelineMessage key={message.id} message={message} />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

interface TimelineMessageProps {
  message: RoundtableMessage;
}

function TimelineMessage({ message }: TimelineMessageProps) {
  const isUser = message.role === "user";
  const isClaude = message.agentType === "claude";
  const isGemini = message.agentType === "gemini";
  const isStreaming = message.isStreaming;

  // Get agent for badge
  const agent = isClaude ? CLAUDE_AGENT : isGemini ? GEMINI_AGENT : null;

  return (
    <div
      className={cn(
        "flex gap-3 animate-in fade-in-50 slide-in-from-bottom-2 duration-300",
        isUser && "flex-row-reverse"
      )}
    >
      {/* Avatar */}
      <div className="flex-shrink-0">
        {isUser ? (
          <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center">
            <User className="h-4 w-4 text-muted-foreground" />
          </div>
        ) : agent ? (
          <AgentAvatar agent={agent} size="md" isActive={isStreaming} />
        ) : (
          <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center">
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </div>
        )}
      </div>

      {/* Message content */}
      <div
        className={cn(
          "flex-1 max-w-[85%] rounded-2xl px-4 py-3",
          isUser &&
            "bg-primary text-primary-foreground ml-auto",
          isClaude &&
            "bg-gradient-to-r from-orange-50 to-amber-50 border border-orange-200/60 dark:from-orange-950/40 dark:to-amber-950/30 dark:border-orange-800/40",
          isGemini &&
            "bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200/60 dark:from-blue-950/40 dark:to-indigo-950/30 dark:border-blue-800/40",
          !isUser && !isClaude && !isGemini && "bg-muted"
        )}
      >
        {/* Agent name header */}
        {!isUser && (isClaude || isGemini) && (
          <div className="flex items-center gap-2 mb-1.5">
            <span
              className={cn(
                "text-xs font-semibold tracking-tight",
                isClaude && "text-orange-600 dark:text-orange-400",
                isGemini && "text-blue-600 dark:text-blue-400"
              )}
            >
              {isClaude ? "Claude" : "Gemini"}
            </span>
            {isStreaming && (
              <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
            )}
          </div>
        )}

        {/* Message text */}
        <div
          className={cn(
            "text-sm whitespace-pre-wrap break-words",
            isUser && "text-primary-foreground",
            isClaude && "text-orange-900 dark:text-orange-100",
            isGemini && "text-blue-900 dark:text-blue-100"
          )}
        >
          {message.content}
          {isStreaming && (
            <span className="inline-block w-1.5 h-4 ml-0.5 bg-current animate-pulse" />
          )}
        </div>

        {/* Tokens badge */}
        {message.tokens && !isStreaming && (
          <div className="mt-2 text-xs text-muted-foreground opacity-60">
            {message.tokens.toLocaleString()} tokens
          </div>
        )}
      </div>
    </div>
  );
}
