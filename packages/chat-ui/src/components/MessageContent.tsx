import { useState } from "react";
import { Pencil, History, ChevronDown, ChevronUp, Forward } from "lucide-react";
import type { ChatMessage } from "../types/chat";
import { cn } from "../lib/utils";
import { TruncationIndicator } from "./truncation-indicator";
import { detectMentionedModel } from "./message-utils";
import { MarkdownContent } from "./MarkdownContent";
import { MessageRuntimeDetails } from "./MessageRuntimeDetails";

interface MessageContentProps {
  message: ChatMessage;
  isUser: boolean;
  isStreaming: boolean;
  onContinueAs?: (model: string, prompt: string) => void;
}

export function MessageContent({
  message,
  isUser,
  isStreaming,
  onContinueAs,
}: MessageContentProps) {
  const [showHistory, setShowHistory] = useState(false);
  const mentionedModel = !isUser && message.content ? detectMentionedModel(message.content) : null;

  return (
    <>
      {isUser ? (
        <div className="whitespace-pre-wrap break-words">
          {message.content}
        </div>
      ) : (
        <div className="break-words">
          <MarkdownContent content={message.content} />
          {isStreaming && (
            <span className="inline-block w-2 h-4 ml-1 bg-current animate-pulse" />
          )}
        </div>
      )}

      {message.edited && (
        <div className="mt-1 flex items-center gap-1 text-xs opacity-60">
          <Pencil className="h-3 w-3" />
          <span>edited</span>
          {message.previousVersions && message.previousVersions.length > 0 && (
            <button
              data-testid="history-toggle"
              onClick={() => setShowHistory(!showHistory)}
              className="ml-1 flex items-center gap-0.5 hover:opacity-80"
            >
              <History className="h-3 w-3" />
              {showHistory ? (
                <ChevronUp className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
            </button>
          )}
        </div>
      )}

      {showHistory && message.previousVersions && (
        <div className="mt-2 pt-2 border-t border-current/20 text-xs opacity-60 space-y-1">
          <p className="font-medium">Previous versions:</p>
          {message.previousVersions.map((version, i) => (
            <p key={i} className="pl-2 border-l-2 border-current/30">
              {version}
            </p>
          ))}
        </div>
      )}

      {message.cancelled && (
        <div className="mt-2 text-xs text-yellow-400 font-medium">
          [cancelled]
        </div>
      )}

      {message.truncated && (
        <TruncationIndicator
          outputTokens={message.outputTokens}
          maxTokensRequested={message.maxTokensRequested}
          modelLimit={message.modelLimit}
          truncationWarning={message.truncationWarning}
        />
      )}

      <MessageRuntimeDetails message={message} />

      {!isUser && !isStreaming && mentionedModel && onContinueAs && (
        <button
          onClick={() => onContinueAs(mentionedModel.model, "Continue the conversation")}
          className={cn(
            "mt-3 flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium",
            "bg-slate-800 hover:bg-slate-700",
            "text-slate-300 transition-colors"
          )}
        >
          <Forward className="h-3.5 w-3.5" />
          Continue as @{mentionedModel.alias}
        </button>
      )}
    </>
  );
}
