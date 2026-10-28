import { useState } from "react";
import { Brain, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "../lib/utils";

/**
 * The thinking block's accent. A host themes it by setting `--chat-ui-thinking` (any CSS color); the default is the
 * violet the block always had. The box tints and the body text are mixed from it.
 */
const ACCENT = "var(--chat-ui-thinking, oklch(71.4% 0.203 305.504))";
const boxStyle = {
  backgroundColor: `color-mix(in oklab, ${ACCENT} 12%, transparent)`,
  borderColor: `color-mix(in oklab, ${ACCENT} 25%, transparent)`,
  color: `color-mix(in oklab, ${ACCENT} 45%, white)`,
};

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
  const isThinkingOnly = isStreaming && !hasContent;
  // Open while the model is only thinking, folded once it answers; a click overrides either.
  const [chosen, setChosen] = useState<boolean | null>(null);
  const showThinking = chosen ?? isThinkingOnly;

  return (
    <div className="mb-3">
      <button
        data-testid="thinking-toggle"
        onClick={() => setChosen(!showThinking)}
        aria-expanded={showThinking}
        style={{ color: ACCENT }}
        className="flex items-center gap-1.5 text-xs transition-opacity hover:opacity-80"
      >
        <Brain className={cn("h-3.5 w-3.5", isThinkingOnly && "animate-pulse")} />
        <span className="font-medium">
          {isThinkingOnly ? "Thinking..." : "Thinking"}
        </span>
        {!isStreaming && thinkingTokens && (
          <span className="opacity-80">
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
        <div
          data-testid="thinking-body"
          style={boxStyle}
          className="mt-2 p-3 rounded-md border text-sm whitespace-pre-wrap"
        >
          {thinking}
          {isThinkingOnly && (
            <span className="inline-block w-2 h-4 ml-1 animate-pulse" style={{ backgroundColor: ACCENT }} />
          )}
        </div>
      )}
    </div>
  );
}
