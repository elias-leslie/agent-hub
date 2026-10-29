import type { ChatCompaction, ChatMessage } from "../../types/chat";
import { compactCount, formatUsd } from "./tool-format";

/** "Context compacted · 9.2k → 6.4k tokens", or the failure; sizes the server did not report are left out, never 0. */
export function compactionText(compaction: ChatCompaction): string {
  if (compaction.status !== "ok") return "Context compaction failed";
  const { tokensBefore, tokensAfter } = compaction;
  if (tokensBefore !== undefined && tokensAfter !== undefined) {
    return `Context compacted · ${compactCount(tokensBefore)} → ${compactCount(tokensAfter)} tokens`;
  }
  return "Context compacted";
}

/** What the line's tooltip adds: how many messages were summarized, by which model, at what cost. */
export function compactionDetail(compaction: ChatCompaction): string | undefined {
  const parts = [
    compaction.messagesSummarized !== undefined ? `${compaction.messagesSummarized} earlier messages summarized` : null,
    compaction.summarizerModel ? `by ${compaction.summarizerModel}` : null,
    compaction.costUsd !== undefined && compaction.costUsd > 0 ? formatUsd(compaction.costUsd) : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" ") : undefined;
}

/** The note where the history was summarized: one muted line, like the other system lines. */
export function CompactionLine({ message }: { message: ChatMessage }) {
  const compaction = message.compaction;
  if (!compaction) return null;
  return (
    <div data-testid="compaction-line" title={compactionDetail(compaction)} className="mb-4 text-xs text-muted-foreground">
      {compactionText(compaction)}
    </div>
  );
}
