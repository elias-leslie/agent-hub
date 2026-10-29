import { useState } from "react";
import { Brain, ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "../lib/utils";
import { formatSeconds } from "./transcript/tool-format";

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
  /** How long the model thought, when known: the transcript layout says "Thought for 8s". */
  thinkingMs?: number;
  isStreaming: boolean;
  hasContent: boolean;
  /** `card` is the tinted box; `transcript` is one dim line that unfolds into text with a left rule. */
  variant?: "card" | "transcript";
}

/** "Thought for 8s", else "Thought" with the token count when only that is known. */
export function thoughtLabel(thinkingMs: number | undefined, thinkingTokens: number | undefined): string {
  if (thinkingMs !== undefined && thinkingMs >= 500) return `Thought for ${formatSeconds(thinkingMs / 1000)}`;
  if (thinkingTokens) return `Thought (${thinkingTokens.toLocaleString()} tokens)`;
  return "Thought";
}

export function ThinkingBlock({
  thinking,
  thinkingTokens,
  thinkingMs,
  isStreaming,
  hasContent,
  variant = "card",
}: ThinkingBlockProps) {
  const isThinkingOnly = isStreaming && !hasContent;
  // Open while the model is only thinking, folded once it answers; a click overrides either.
  const [chosen, setChosen] = useState<boolean | null>(null);
  const showThinking = chosen ?? isThinkingOnly;

  if (variant === "transcript") {
    return (
      <div className="mb-2.5" data-testid="thinking-fold">
        <button
          type="button"
          data-testid="thinking-toggle"
          onClick={() => setChosen(!showThinking)}
          aria-expanded={showThinking}
          className="flex items-center gap-2 rounded-sm text-[13px] text-muted-foreground/80 transition-colors hover:text-muted-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          <span aria-hidden className={cn("inline-block text-[10px] transition-transform", showThinking && "rotate-90")}>
            {"\u25b8"}
          </span>
          <span className={cn(isThinkingOnly && "animate-pulse motion-reduce:animate-none")}>
            {isThinkingOnly ? "Thinking\u2026" : thoughtLabel(thinkingMs, thinkingTokens)}
          </span>
        </button>
        {showThinking && (
          <div
            data-testid="thinking-body"
            className="ml-[5px] mt-1.5 border-l border-border pl-3 text-[13px] leading-relaxed whitespace-pre-wrap text-muted-foreground"
          >
            {thinking}
          </div>
        )}
      </div>
    );
  }

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
