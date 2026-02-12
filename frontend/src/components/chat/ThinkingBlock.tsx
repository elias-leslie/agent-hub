import { useState } from "react";
import { Brain, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";

interface ThinkingBlockProps {
  thinking: string;
  thinkingTokens?: number;
  isStreaming: boolean;
  hasContent: boolean;
}

export function ThinkingBlock({
  thinking,
  thinkingTokens,
  isStreaming,
  hasContent,
}: ThinkingBlockProps) {
  const [showThinking, setShowThinking] = useState(false);
  const isThinkingOnly = isStreaming && !hasContent;

  return (
    <div className="mb-3">
      <button
        data-testid="thinking-toggle"
        onClick={() => setShowThinking(!showThinking)}
        className="flex items-center gap-1.5 text-xs text-purple-600 dark:text-purple-400 hover:text-purple-700 dark:hover:text-purple-300 transition-colors"
      >
        <Brain className={cn("h-3.5 w-3.5", isThinkingOnly && "animate-pulse")} />
        <span className="font-medium">
          {isThinkingOnly ? "Thinking..." : "Thinking"}
        </span>
        {!isStreaming && thinkingTokens && (
          <span className="text-purple-400 dark:text-purple-500">
            ({thinkingTokens.toLocaleString()} tokens)
          </span>
        )}
        {showThinking ? (
          <ChevronUp className="h-3 w-3" />
        ) : (
          <ChevronDown className="h-3 w-3" />
        )}
      </button>
      {showThinking && (
        <div className="mt-2 p-3 rounded-md bg-purple-50 dark:bg-purple-950/30 border border-purple-100 dark:border-purple-900/50 text-sm text-purple-800 dark:text-purple-200 whitespace-pre-wrap">
          {thinking}
          {isThinkingOnly && (
            <span className="inline-block w-2 h-4 ml-1 bg-purple-500 animate-pulse" />
          )}
        </div>
      )}
    </div>
  );
}
