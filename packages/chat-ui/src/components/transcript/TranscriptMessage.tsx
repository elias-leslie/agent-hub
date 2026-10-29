import type { ChatMessage, ToolExecution } from "../../types/chat";
import { MarkdownContent } from "../MarkdownContent";
import { TruncationIndicator } from "../truncation-indicator";
import { ThinkingBlock } from "../ThinkingBlock";
import { CompactionLine } from "./CompactionLine";
import { ToolLine } from "./ToolLine";

/** The answer's text and tool calls in the order they happened: text up to each call's offset, then the call. */
export function interleave(content: string, tools: ToolExecution[]): Array<{ text: string } | { tools: ToolExecution[] }> {
  const placed = tools.length > 0 && tools.every((tool) => typeof tool.contentOffset === "number");
  if (!placed) {
    // An answer stored before offsets were recorded has none: its calls come first, then the text. No order is invented.
    return [...(tools.length > 0 ? [{ tools }] : []), ...(content.trim() ? [{ text: content }] : [])];
  }
  const out: Array<{ text: string } | { tools: ToolExecution[] }> = [];
  let cursor = 0;
  let pending: ToolExecution[] = [];
  const flush = () => {
    if (pending.length > 0) out.push({ tools: pending });
    pending = [];
  };
  for (const tool of tools) {
    const offset = Math.min(content.length, Math.max(cursor, tool.contentOffset as number));
    if (offset > cursor) {
      const chunk = content.slice(cursor, offset);
      if (chunk.trim()) {
        flush();
        out.push({ text: chunk });
      }
      cursor = offset;
    }
    pending.push(tool);
  }
  flush();
  const rest = content.slice(cursor);
  if (rest.trim()) out.push({ text: rest });
  return out;
}

/** Your message: a thin amber edge, a faint tint, a small label. No bubble. */
function UserEntry({ message }: { message: ChatMessage }) {
  return (
    <div
      data-testid="user-entry"
      className="mb-5 mt-1.5 whitespace-pre-wrap break-words rounded-r-md border-l-2 border-primary bg-primary/5 px-3.5 py-2.5 text-sm leading-6 text-foreground"
    >
      <div className="mb-0.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-primary">You</div>
      {message.content}
    </div>
  );
}

/** The agent's turn: thinking folded, tool calls as lines, text as plain prose. No card around it. */
function AgentEntry({ message, isStreaming }: { message: ChatMessage; isStreaming: boolean }) {
  const tools = message.toolExecutions ?? [];
  const parts = interleave(message.content, tools);
  const retries = message.retries ?? [];
  const showNotes = message.cancelled || message.fallbackUsed || retries.length > 0;
  return (
    <div data-testid="agent-entry" id={`msg-${message.id}`} className="mb-4">
      {message.thinking ? (
        <ThinkingBlock
          variant="transcript"
          thinking={message.thinking}
          thinkingTokens={message.thinkingTokens}
          thinkingMs={message.thinkingMs}
          isStreaming={isStreaming && message.statusLabel === "Thinking"}
          hasContent={false}
        />
      ) : null}
      {parts.map((part, index) =>
        "tools" in part ? (
          <div key={`t${index}`} className="mb-2 space-y-1.5">
            {part.tools.map((tool) => (
              <ToolLine key={tool.id} tool={tool} />
            ))}
          </div>
        ) : (
          <MarkdownContent key={`p${index}`} content={part.text} className="mb-2.5" />
        ),
      )}
      {message.truncated ? (
        <TruncationIndicator
          outputTokens={message.outputTokens}
          maxTokensRequested={message.maxTokensRequested}
          modelLimit={message.modelLimit}
          truncationWarning={message.truncationWarning}
        />
      ) : null}
      {showNotes ? (
        <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted-foreground" data-testid="message-notes">
          {message.cancelled ? <span>Stopped</span> : null}
          {message.fallbackUsed ? <span title={message.fallbackReason ?? undefined}>A fallback model answered</span> : null}
          {retries.map((retry, index) => (
            <span key={index} title={retry.reason}>
              Retried {retry.attempt ?? "?"} of {retry.max ?? "?"}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function TranscriptMessage({ message, isStreaming }: { message: ChatMessage; isStreaming: boolean }) {
  if (message.role === "user") return <UserEntry message={message} />;
  if (message.kind === "compaction") return <CompactionLine message={message} />;
  if (message.role === "system") {
    return <div className="mb-4 text-xs text-muted-foreground whitespace-pre-wrap">{message.content}</div>;
  }
  return <AgentEntry message={message} isStreaming={isStreaming} />;
}
