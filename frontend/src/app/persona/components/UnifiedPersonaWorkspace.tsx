"use client";

import Link from "next/link";
import {
  useDeferredValue,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  startTransition,
} from "react";
import {
  Search,
  Loader2,
  HeartPulse,
  Wrench,
  Bot,
  Sparkles,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  ArrowDown,
  ArrowUp,
  Clock3,
  Radio,
} from "lucide-react";
import {
  MessageBubble,
  MessageInput,
  useChatStream,
  type ChatMessage,
} from "@agent-hub/chat-ui";

import { SessionDropdown } from "@/components/chat/session-dropdown";
import { useSessionEvents } from "@/hooks/use-session-events";
import { cn } from "@/lib/utils";
import { INTERNAL_HEADERS, fetchApi, getApiBaseUrl, getSseBaseUrl, getWsUrl } from "@/lib/api-config";
import {
  type PersonaStreamMatch,
  fetchPersonaStream,
  type PersonaStreamEventPreview,
  type PersonaStreamEntry,
} from "@/lib/api/persona-stream";
import type { SessionEvent as LiveSessionEvent } from "@/types/events";
import { TimeRangeDropdown, type TimeRange } from "./TimeRangeDropdown";

const PROJECT_ID = "persona-sandbox";
const PAGE_SIZE = 120;
const LIVE_REFRESH_MS = 5_000;
const AUTO_FOLLOW_BOTTOM_THRESHOLD = 160;
const PROGRAMMATIC_SCROLL_GRACE_MS = 400;

type FilterMode = "all" | "messages" | "work" | "errors" | "heartbeats";

interface UnifiedPersonaWorkspaceProps {
  agentSlug: string;
  activeSessionId: string | null;
  sidebarRefreshTrigger: number;
  onSelectSession: (sessionId: string | null) => void;
  onSessionCreated: (sessionId: string) => void;
  onNewSession: () => void;
}

type FeedMessage = { kind: "message"; id: string; sessionId: string | null; timestamp: Date; message: ChatMessage };
type FeedHeartbeat = {
  kind: "heartbeat";
  id: string;
  sessionId: string;
  timestamp: Date;
  entry: PersonaStreamEntry;
};
type FeedChildRun = {
  kind: "child_run";
  id: string;
  sessionId: string;
  timestamp: Date;
  entry: PersonaStreamEntry;
};
type FeedAnchor = FeedMessage | FeedHeartbeat | FeedChildRun;
type FeedItem = FeedAnchor;

interface ItemTimelineBlock {
  kind: "item";
  anchorItem: FeedAnchor;
  childRuns: FeedChildRun[];
}

interface RoutineHeartbeatTimelineBlock {
  kind: "routine_group";
  id: string;
  items: Array<{
    anchorItem: FeedHeartbeat;
    childRuns: FeedChildRun[];
  }>;
}

type TimelineBlock = ItemTimelineBlock | RoutineHeartbeatTimelineBlock;

interface LiveSessionPatch {
  liveSummary: string | null;
  liveStatus: string | null;
  eventPreviews: PersonaStreamEventPreview[];
}

function isChildRunItem(item: FeedItem): item is FeedChildRun {
  return item.kind === "child_run";
}

function canAnchorChildRuns(item: FeedAnchor): item is FeedMessage | FeedHeartbeat {
  return item.kind !== "child_run";
}

function buildChatMessage(entry: PersonaStreamEntry): ChatMessage {
  return {
    id: entry.id,
    role: (entry.role as ChatMessage["role"]) || "assistant",
    content: entry.content || "",
    timestamp: new Date(entry.timestamp),
    agentName: entry.agent_slug || undefined,
    agentModel: entry.model || undefined,
    agentProvider: "claude",
  };
}

function buildLocalFeedMessages(messages: ChatMessage[], currentSessionId: string | null): FeedItem[] {
  return messages.map((message) => ({
    kind: "message" as const,
    id: message.id,
    sessionId: currentSessionId,
    timestamp: message.timestamp,
    message,
  }));
}

function buildRemoteFeedItems(entries: PersonaStreamEntry[]): FeedItem[] {
  return entries.map((entry) => {
    if (entry.entry_type === "message") {
      return {
        kind: "message" as const,
        id: entry.id,
        sessionId: entry.session_id,
        timestamp: new Date(entry.timestamp),
        message: buildChatMessage(entry),
      };
    }
    return {
      kind: entry.entry_type,
      id: entry.id,
      sessionId: entry.session_id,
      timestamp: new Date(entry.timestamp),
      entry,
    };
  });
}

function DateDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 py-4">
      <div className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
      <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
        {label}
      </span>
      <div className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
    </div>
  );
}

function formatDayLabel(date: Date): string {
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatTimeLabel(date: Date): string {
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatTimestampTitle(date: Date): string {
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function TimelineTimestamp({ timestamp }: { timestamp: Date }) {
  const label = formatTimeLabel(timestamp);
  const title = formatTimestampTitle(timestamp);

  return (
    <time
      dateTime={timestamp.toISOString()}
      title={title}
      className="shrink-0 pt-2 text-[11px] font-medium tabular-nums tracking-[0.08em] text-slate-400 dark:text-slate-500"
    >
      {label}
    </time>
  );
}

function formatDurationLabel(durationMs: number | null): string | null {
  if (durationMs == null) {
    return null;
  }
  if (durationMs < 1000) {
    return `${durationMs}ms`;
  }
  if (durationMs < 60_000) {
    return `${(durationMs / 1000).toFixed(1)}s`;
  }
  const minutes = Math.floor(durationMs / 60_000);
  const seconds = Math.floor((durationMs % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function parseJsonPreview(value: string | null): Record<string, unknown> | null {
  if (!value) {
    return null;
  }
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function shortenText(value: string, maxLength = 88): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 1)}…`;
}

function highlightKeywordClass(token: string): string {
  const normalized = token.toLowerCase();
  if (["error", "failed", "failure", "blocked"].includes(normalized)) {
    return "rounded-md bg-rose-100 px-1 py-0.5 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300";
  }
  if (["warning", "warn", "paused"].includes(normalized)) {
    return "rounded-md bg-amber-100 px-1 py-0.5 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300";
  }
  if (["success", "succeeded", "completed", "ok"].includes(normalized)) {
    return "rounded-md bg-emerald-100 px-1 py-0.5 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300";
  }
  if (["running", "working", "active"].includes(normalized)) {
    return "rounded-md bg-sky-100 px-1 py-0.5 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300";
  }
  return "";
}

function HighlightedText({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const parts = text.split(/(\b(?:error|failed|failure|warning|warn|success|succeeded|completed|ok|running|working|active|blocked|paused)\b)/gi);

  return (
    <span className={className}>
      {parts.map((part, index) => {
        const keywordClass = highlightKeywordClass(part);
        if (!keywordClass) {
          return <span key={`${part}-${index}`}>{part}</span>;
        }
        return (
          <span key={`${part}-${index}`} className={keywordClass}>
            {part}
          </span>
        );
      })}
    </span>
  );
}

function eventLabel(eventType: string): string {
  return eventType.replaceAll("_", " ");
}

function isNearBottom(container: HTMLDivElement): boolean {
  const distanceFromBottom = container.scrollHeight - container.clientHeight - container.scrollTop;
  return distanceFromBottom <= AUTO_FOLLOW_BOTTOM_THRESHOLD;
}

function eventToneClasses(eventType: string): string {
  if (eventType === "error") {
    return "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-300";
  }
  if (eventType === "tool_result") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300";
  }
  if (eventType === "tool_use") {
    return "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900 dark:bg-sky-950/30 dark:text-sky-300";
  }
  if (eventType === "thinking") {
    return "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700 dark:border-fuchsia-900 dark:bg-fuchsia-950/30 dark:text-fuchsia-300";
  }
  return "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-950/50 dark:text-slate-300";
}

function eventSummaryLabel(preview: PersonaStreamEventPreview): string {
  if (preview.event_type === "assistant_message") {
    return "Assistant";
  }
  if (preview.event_type === "user_message") {
    return "User";
  }
  if (preview.event_type === "system_message") {
    return "System";
  }
  if (preview.event_type === "tool_use") {
    return "Tool call";
  }
  if (preview.event_type === "tool_result") {
    return "Tool result";
  }
  if (preview.event_type === "error") {
    return "Error";
  }
  if (preview.event_type === "thinking") {
    return "Reasoning";
  }
  return eventLabel(preview.event_type);
}

function eventLeadText(preview: PersonaStreamEventPreview): string | null {
  const toolInput = parseJsonPreview(preview.tool_input_preview);
  const toolOutput = parseJsonPreview(preview.tool_output_preview);

  if (preview.event_type === "tool_use" && toolInput) {
    const command = toolInput.command;
    if (typeof command === "string" && command.trim()) {
      return shortenText(command.trim(), 104);
    }
    const filePath = toolInput.file_path ?? toolInput.path;
    if (typeof filePath === "string" && filePath.trim()) {
      return shortenText(filePath.trim(), 104);
    }
    const action = toolInput.action;
    const taskId = toolInput.task_id;
    if (typeof action === "string" && action.trim()) {
      return typeof taskId === "string" && taskId.trim()
        ? `${action} ${taskId}`
        : action;
    }
    const description = toolInput.description;
    if (typeof description === "string" && description.trim()) {
      return shortenText(description.trim(), 104);
    }
  }

  if (preview.event_type === "tool_result" && toolOutput) {
    const content = toolOutput.content;
    if (typeof content === "string" && content.trim()) {
      return shortenText(content.trim(), 104);
    }
  }

  if (preview.content_preview) {
    return shortenText(preview.content_preview.trim(), 104);
  }

  return null;
}

function eventAccentClasses(preview: PersonaStreamEventPreview): string {
  if (preview.event_type === "error") {
    return "bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300";
  }
  if (preview.event_type === "tool_result") {
    return "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300";
  }
  if (preview.event_type === "tool_use") {
    return "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300";
  }
  if (preview.event_type === "assistant_message") {
    return "bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-950/40 dark:text-fuchsia-300";
  }
  return "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300";
}

function heartbeatIsImportant(entry: PersonaStreamEntry): boolean {
  const summary = `${entry.summary_oneliner ?? ""} ${entry.live_summary ?? ""}`.toLowerCase();
  const importantKeywords = [
    "dispatch",
    "publish",
    "verified",
    "verify",
    "fixed",
    "created ",
    "reconciled",
    "merged",
    "review",
    "audit",
    "error",
    "failed",
    "blocked",
    "warning",
    "assess",
    "investig",
    "task-",
  ];
  return importantKeywords.some((keyword) => summary.includes(keyword));
}

function isRoutineHeartbeatBlock(
  block: ItemTimelineBlock,
  searchActive: boolean,
  filterMode: FilterMode,
): boolean {
  if (searchActive || filterMode !== "all") {
    return false;
  }
  if (block.anchorItem.kind !== "heartbeat") {
    return false;
  }
  if (block.childRuns.length > 0) {
    return false;
  }
  const entry = block.anchorItem.entry;
  if (entry.status !== "completed" || entry.live_status === "active") {
    return false;
  }
  if (entry.event_previews.some((preview) => preview.event_type === "error")) {
    return false;
  }
  if (heartbeatIsImportant(entry)) {
    return false;
  }
  const summary = `${entry.summary_oneliner ?? ""} ${entry.live_summary ?? ""}`.toLowerCase();
  return entry.tool_count <= 3 || summary.includes("waiting for model") || summary.includes("execution completed");
}

function mergeEventPreviews(
  original: PersonaStreamEventPreview[],
  live: PersonaStreamEventPreview[],
): PersonaStreamEventPreview[] {
  if (live.length === 0) {
    return original;
  }
  const deduped = new Map<string, PersonaStreamEventPreview>();
  for (const preview of [...live, ...original]) {
    if (!deduped.has(preview.id)) {
      deduped.set(preview.id, preview);
    }
  }
  return Array.from(deduped.values()).slice(0, 12);
}

function buildLivePreview(event: LiveSessionEvent): PersonaStreamEventPreview | null {
  const previewId = `live:${event.session_id}:${event.timestamp}:${event.event_type}`;
  if (event.event_type === "message") {
    const role =
      typeof event.data === "object" && event.data && "role" in event.data && typeof event.data.role === "string"
        ? event.data.role
        : null;
    const content =
      typeof event.data === "object" && event.data && "content" in event.data && typeof event.data.content === "string"
        ? event.data.content
        : null;
    return {
      id: previewId,
      event_type: role ? `${role}_message` : "assistant_message",
      created_at: event.timestamp,
      role,
      tool_name: null,
      content_preview: content,
      tool_input_preview: null,
      tool_output_preview: null,
      duration_ms: null,
      model_used: null,
    };
  }
  if (event.event_type === "tool_use") {
    const toolName =
      typeof event.data === "object" && event.data && "tool_name" in event.data && typeof event.data.tool_name === "string"
        ? event.data.tool_name
        : null;
    const toolInput =
      typeof event.data === "object" && event.data && "tool_input" in event.data
        ? JSON.stringify(event.data.tool_input)
        : null;
    const toolOutput =
      typeof event.data === "object" && event.data && "tool_output" in event.data
        ? JSON.stringify(event.data.tool_output)
        : null;
    return {
      id: previewId,
      event_type: "tool_use",
      created_at: event.timestamp,
      role: null,
      tool_name: toolName,
      content_preview: null,
      tool_input_preview: toolInput,
      tool_output_preview: toolOutput,
      duration_ms: null,
      model_used: null,
    };
  }
  if (event.event_type === "error") {
    const errorMessage =
      typeof event.data === "object" && event.data && "error_message" in event.data && typeof event.data.error_message === "string"
        ? event.data.error_message
        : "Session error";
    return {
      id: previewId,
      event_type: "error",
      created_at: event.timestamp,
      role: null,
      tool_name: null,
      content_preview: errorMessage,
      tool_input_preview: null,
      tool_output_preview: null,
      duration_ms: null,
      model_used: null,
    };
  }
  if (event.event_type === "complete") {
    return {
      id: previewId,
      event_type: "tool_result",
      created_at: event.timestamp,
      role: null,
      tool_name: null,
      content_preview: "Execution completed",
      tool_input_preview: null,
      tool_output_preview: null,
      duration_ms: null,
      model_used: null,
    };
  }
  return null;
}

function liveSummaryFromEvent(event: LiveSessionEvent): string | null {
  if (event.event_type === "tool_use") {
    const toolName =
      typeof event.data === "object" && event.data && "tool_name" in event.data && typeof event.data.tool_name === "string"
        ? event.data.tool_name
        : "tool";
    return `Running ${toolName}`;
  }
  if (event.event_type === "message") {
    const content =
      typeof event.data === "object" && event.data && "content" in event.data && typeof event.data.content === "string"
        ? event.data.content
        : null;
    return content ? shortenText(content, 96) : "New message";
  }
  if (event.event_type === "error") {
    const errorMessage =
      typeof event.data === "object" && event.data && "error_message" in event.data && typeof event.data.error_message === "string"
        ? event.data.error_message
        : "Session error";
    return `Error: ${shortenText(errorMessage, 88)}`;
  }
  if (event.event_type === "complete") {
    return "Execution completed";
  }
  if (event.event_type === "session_start") {
    return "Session started";
  }
  return null;
}

function liveStatusFromEvent(event: LiveSessionEvent): string | null {
  if (event.event_type === "complete") {
    return "completed";
  }
  if (event.event_type === "error") {
    return "failed";
  }
  return "active";
}

function PreviewCodeBlock({
  label,
  value,
}: {
  label: string;
  value: string | null;
}) {
  if (!value) {
    return null;
  }

  return (
    <div className="mt-2 rounded-xl border border-slate-200 bg-white/80 p-2 dark:border-slate-800 dark:bg-slate-900/80">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
        {label}
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs text-slate-700 dark:text-slate-200">
        {value}
      </pre>
    </div>
  );
}

function EventPreviewList({ previews }: { previews: PersonaStreamEventPreview[] }) {
  return (
    <div className="mt-3 space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
      {previews.map((preview) => {
        const duration = formatDurationLabel(preview.duration_ms);
        const leadText = eventLeadText(preview);
        return (
          <div
            key={preview.id}
            className={cn("rounded-xl border px-3 py-2 text-sm", eventToneClasses(preview.event_type))}
          >
            <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.14em]">
              <span className={cn("rounded-full px-2 py-0.5", eventAccentClasses(preview))}>
                {eventSummaryLabel(preview)}
              </span>
              <time dateTime={preview.created_at} className="inline-flex items-center gap-1 normal-case tracking-normal opacity-80">
                <Clock3 className="h-3 w-3" />
                {formatTimeLabel(new Date(preview.created_at))}
              </time>
              {preview.tool_name && <span className="normal-case tracking-normal font-medium">{preview.tool_name}</span>}
              {duration && <span className="normal-case tracking-normal opacity-80">{duration}</span>}
            </div>
            {leadText && (
              <div className="mt-2 rounded-xl border border-black/5 bg-white/70 px-2.5 py-2 dark:border-white/5 dark:bg-slate-950/60">
                <HighlightedText
                  text={leadText}
                  className="block whitespace-pre-wrap break-words text-xs font-medium"
                />
              </div>
            )}
            {preview.content_preview && (
              <HighlightedText
                text={preview.content_preview}
                className="mt-2 block whitespace-pre-wrap break-words text-sm"
              />
            )}
            <PreviewCodeBlock label="Input" value={preview.tool_input_preview} />
            <PreviewCodeBlock label="Output" value={preview.tool_output_preview} />
          </div>
        );
      })}
    </div>
  );
}

function RoutineHeartbeatGroup({
  block,
  expanded,
  onToggle,
  activeSessionId,
  expandedEntryIds,
  onToggleEntry,
}: {
  block: RoutineHeartbeatTimelineBlock;
  expanded: boolean;
  onToggle: () => void;
  activeSessionId: string | null;
  expandedEntryIds: Record<string, boolean>;
  onToggleEntry: (entryId: string) => void;
}) {
  const first = block.items[0]?.anchorItem;
  const last = block.items.at(-1)?.anchorItem;
  const timeRange =
    first && last
      ? `${formatTimeLabel(first.timestamp)} to ${formatTimeLabel(last.timestamp)}`
      : null;

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/90 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/80">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
              <Clock3 className="h-4 w-4 text-slate-400" />
              {block.items.length} routine heartbeats
            </span>
            {timeRange && (
              <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {timeRange}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Routine checks stay collapsed until you need the full detail.
          </p>
        </div>
        <button
          type="button"
          onClick={onToggle}
          className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-white dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {expanded ? "Hide routine checks" : "Show routine checks"}
        </button>
      </div>
      {expanded && (
        <div className="mt-3 space-y-3 border-t border-slate-200 pt-3 dark:border-slate-800">
          {block.items.map(({ anchorItem }) => (
            <div
              key={anchorItem.id}
              data-session-anchor={anchorItem.sessionId}
              data-testid="stream-item"
              data-stream-item-id={anchorItem.id}
              data-timestamp={anchorItem.timestamp.toISOString()}
              className="flex items-start gap-3"
            >
              <TimelineTimestamp timestamp={anchorItem.timestamp} />
              <div className="min-w-0 flex-1">
                <HeartbeatCard
                  entry={anchorItem.entry}
                  selected={anchorItem.sessionId === activeSessionId}
                  expanded={!!expandedEntryIds[anchorItem.id]}
                  onToggle={() => onToggleEntry(anchorItem.id)}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ChildRunStack({
  childRuns,
  activeSessionId,
  expandedEntryIds,
  onToggle,
  matchedIds,
  activeMatchId,
}: {
  childRuns: FeedChildRun[];
  activeSessionId: string | null;
  expandedEntryIds: Record<string, boolean>;
  onToggle: (entryId: string) => void;
  matchedIds: Set<string>;
  activeMatchId: string | null;
}) {
  return (
    <div className="ml-5 mt-3 border-l border-dashed border-sky-200 pl-4 dark:border-sky-900">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-600 dark:text-sky-300">
        Spawned Agents
      </div>
      <div className="space-y-3">
        {childRuns.map((childRun) => {
          const selected = childRun.sessionId === activeSessionId;
          const matched = matchedIds.has(childRun.id);
          const activeMatched = activeMatchId === childRun.id;

          return (
            <div
              key={childRun.id}
              data-session-anchor={childRun.sessionId}
              data-testid="stream-item"
              data-stream-item-id={childRun.id}
              data-timestamp={childRun.timestamp.toISOString()}
              className={cn(
                "flex items-start gap-3 rounded-2xl",
                matched && "px-2 py-1 ring-1 ring-amber-200 dark:ring-amber-800",
                activeMatched && "ring-2 ring-amber-400 dark:ring-amber-500",
              )}
            >
              <TimelineTimestamp timestamp={childRun.timestamp} />
              <div className="min-w-0 flex-1">
                <ChildRunCard
                  entry={childRun.entry}
                  selected={selected}
                  expanded={!!expandedEntryIds[childRun.id]}
                  onToggle={() => onToggle(childRun.id)}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ChildRunCard({
  entry,
  selected,
  expanded,
  onToggle,
}: {
  entry: PersonaStreamEntry;
  selected: boolean;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border px-4 py-3",
        selected
          ? "border-sky-300 bg-sky-50/70 dark:border-sky-700 dark:bg-sky-950/30"
          : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-full bg-sky-100 p-2 text-sky-700 dark:bg-sky-950/50 dark:text-sky-300">
          <Bot className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {entry.agent_slug || "Agent"} on {entry.project_id}
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {entry.status}
            </span>
            {entry.tool_count > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                <Wrench className="h-3 w-3" />
                {entry.tool_count}
              </span>
            )}
          </div>
          <HighlightedText
            text={entry.summary_oneliner || entry.live_summary || "Child run activity"}
            className="mt-1 block text-sm text-slate-600 dark:text-slate-300"
          />
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400 dark:text-slate-500">
            {entry.external_id && <span>task {entry.external_id}</span>}
            {entry.current_branch && <span>{entry.current_branch}</span>}
            <Link
              href={`/sessions/${entry.session_id}`}
              className="text-sky-600 transition hover:text-sky-500 dark:text-sky-300 dark:hover:text-sky-200"
            >
              open session
            </Link>
          </div>
          {entry.event_previews.length > 0 && (
            <button
              type="button"
              onClick={onToggle}
              className="mt-3 inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
              {expanded ? "Hide run details" : `Show run details (${entry.event_previews.length})`}
            </button>
          )}
          {expanded && <EventPreviewList previews={entry.event_previews} />}
        </div>
      </div>
    </div>
  );
}

function HeartbeatCard({
  entry,
  selected,
  expanded,
  onToggle,
}: {
  entry: PersonaStreamEntry;
  selected: boolean;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border px-4 py-3",
        selected
          ? "border-amber-300 bg-amber-50/80 dark:border-amber-700 dark:bg-amber-950/30"
          : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-full bg-amber-100 p-2 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300">
          <HeartPulse className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Heartbeat
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {entry.status}
            </span>
            {entry.tool_count > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                <Wrench className="h-3 w-3" />
                {entry.tool_count}
              </span>
            )}
          </div>
          <HighlightedText
            text={entry.summary_oneliner || entry.live_summary || "Routine check completed"}
            className="mt-1 block text-sm text-slate-600 dark:text-slate-300"
          />
          {entry.live_summary && entry.summary_oneliner !== entry.live_summary && (
            <HighlightedText
              text={entry.live_summary}
              className="mt-2 block text-xs text-slate-400 dark:text-slate-500"
            />
          )}
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400 dark:text-slate-500">
            <Link
              href={`/sessions/${entry.session_id}`}
              className="text-amber-700 transition hover:text-amber-600 dark:text-amber-300 dark:hover:text-amber-200"
            >
              open session
            </Link>
          </div>
          {entry.event_previews.length > 0 && (
            <button
              type="button"
              onClick={onToggle}
              className="mt-3 inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
              {expanded ? "Hide heartbeat details" : `Show heartbeat details (${entry.event_previews.length})`}
            </button>
          )}
          {expanded && <EventPreviewList previews={entry.event_previews} />}
        </div>
      </div>
    </div>
  );
}

export function UnifiedPersonaWorkspace({
  agentSlug,
  activeSessionId,
  sidebarRefreshTrigger,
  onSelectSession,
  onSessionCreated,
  onNewSession,
}: UnifiedPersonaWorkspaceProps) {
  const searchInputId = useId();
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [search, setSearch] = useState("");
  const [filterMode, setFilterMode] = useState<FilterMode>("all");
  const [autoFollow, setAutoFollow] = useState(true);
  const deferredSearch = useDeferredValue(search);
  const [entries, setEntries] = useState<PersonaStreamEntry[]>([]);
  const [searchMatches, setSearchMatches] = useState<PersonaStreamMatch[]>([]);
  const [matchCount, setMatchCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [focusSessionId, setFocusSessionId] = useState<string | null>(activeSessionId);
  const [anchorEntryId, setAnchorEntryId] = useState<string | null>(null);
  const [expandedEntryIds, setExpandedEntryIds] = useState<Record<string, boolean>>({});
  const [expandedRoutineGroupIds, setExpandedRoutineGroupIds] = useState<Record<string, boolean>>({});
  const [activeSearchMatchId, setActiveSearchMatchId] = useState<string | null>(null);
  const [liveRefreshTick, setLiveRefreshTick] = useState(0);
  const [liveSessionPatches, setLiveSessionPatches] = useState<Record<string, LiveSessionPatch>>({});
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoFollowRef = useRef(true);
  const programmaticScrollUntilRef = useRef(0);

  const apiConfig = useMemo(
    () => ({
      fetchHeaders: INTERNAL_HEADERS,
      completeEndpoint: `${getSseBaseUrl()}/api/complete`,
      sessionsEndpoint: `${getApiBaseUrl()}/api/sessions`,
      preferencesEndpoint: "/api/preferences",
      fetchFn: fetchApi,
      projectId: PROJECT_ID,
      memoryGroupPrefix: "agent:",
    }),
    [],
  );

  const {
    messages,
    status,
    error: chatError,
    currentSessionId,
    sendMessage,
    cancelStream,
  } = useChatStream({
    agentSlug,
    sessionId: activeSessionId || undefined,
    toolsEnabled: true,
    apiConfig,
    loadInitialSession: false,
  } as any);

  useEffect(() => {
    autoFollowRef.current = autoFollow;
  }, [autoFollow]);

  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    const container = scrollRef.current;
    if (!container || typeof container.scrollTo !== "function") {
      return;
    }
    programmaticScrollUntilRef.current = Date.now() + PROGRAMMATIC_SCROLL_GRACE_MS;
    container.scrollTo({ top: container.scrollHeight, behavior });
  };

  const hydratedEntries = useMemo(
    () =>
      entries.map((entry) => {
        const patch = liveSessionPatches[entry.session_id];
        if (!patch) {
          return entry;
        }
        return {
          ...entry,
          live_summary: patch.liveSummary ?? entry.live_summary,
          live_status: patch.liveStatus ?? entry.live_status,
          status:
            patch.liveStatus === "failed"
              ? "failed"
              : patch.liveStatus === "completed" && entry.status === "active"
                ? "completed"
                : entry.status,
          event_previews: mergeEventPreviews(entry.event_previews, patch.eventPreviews),
        };
      }),
    [entries, liveSessionPatches],
  );

  const activeStreamSessionIds = useMemo(() => {
    const activeIds = new Set<string>();
    for (const entry of hydratedEntries) {
      if (entry.status === "active" || entry.live_status === "active") {
        activeIds.add(entry.session_id);
      }
    }
    return Array.from(activeIds);
  }, [hydratedEntries]);

  useSessionEvents({
    sessionIds: activeStreamSessionIds,
    autoConnect: true,
    autoReconnect: true,
    onEvent: (event) => {
      const preview = buildLivePreview(event);
      const liveSummary = liveSummaryFromEvent(event);
      const liveStatus = liveStatusFromEvent(event);
      setLiveSessionPatches((current) => {
        const existing = current[event.session_id] ?? {
          liveSummary: null,
          liveStatus: null,
          eventPreviews: [],
        };
        return {
          ...current,
          [event.session_id]: {
            liveSummary: liveSummary ?? existing.liveSummary,
            liveStatus: liveStatus ?? existing.liveStatus,
            eventPreviews: preview ? mergeEventPreviews(existing.eventPreviews, [preview]) : existing.eventPreviews,
          },
        };
      });
      if (!entries.some((entry) => entry.session_id === event.session_id)) {
        setLiveRefreshTick((value) => value + 1);
        return;
      }
      if (event.event_type === "complete" || event.event_type === "error") {
        window.setTimeout(() => {
          setLiveRefreshTick((value) => value + 1);
        }, 600);
      }
    },
  });

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) {
      return;
    }
    const handleScroll = () => {
      if (Date.now() < programmaticScrollUntilRef.current) {
        return;
      }
      if (autoFollowRef.current && !isNearBottom(container)) {
        setAutoFollow(false);
      }
    };
    container.addEventListener("scroll", handleScroll, { passive: true });
    return () => container.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    if (currentSessionId) {
      onSessionCreated(currentSessionId);
    }
  }, [currentSessionId, onSessionCreated]);

  useEffect(() => {
    setFocusSessionId(activeSessionId);
  }, [activeSessionId]);

  useEffect(() => {
    if (!deferredSearch.trim()) {
      setAnchorEntryId(null);
    }
    setPage(1);
  }, [timeRange, deferredSearch, focusSessionId, currentSessionId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const effectiveRange = deferredSearch.trim() ? "all" : timeRange;
      fetchPersonaStream({
      timeRange: effectiveRange,
      search: deferredSearch.trim() || undefined,
      focusSessionId,
      anchorEntryId,
      page,
      pageSize: PAGE_SIZE,
    })
      .then((data) => {
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setEntries((prev) => {
            if (page === 1) {
              return data.entries;
            }
            const merged = [...prev];
            for (const entry of data.entries) {
              if (!merged.some((existing) => existing.id === entry.id)) {
                merged.push(entry);
              }
            }
            return merged;
          });
          setTotal(data.total);
          setSearchMatches(data.matches);
          setMatchCount(data.match_count);
          setError(null);
        });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load stream");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [timeRange, deferredSearch, focusSessionId, anchorEntryId, page, currentSessionId, sidebarRefreshTrigger, liveRefreshTick]);

  useEffect(() => {
    if (!focusSessionId) {
      return;
    }
    const timeout = window.setTimeout(() => {
      const nodes = document.querySelectorAll<HTMLElement>(`[data-session-anchor="${focusSessionId}"]`);
      const target = nodes.length > 0 ? nodes[nodes.length - 1] : null;
      target?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timeout);
  }, [entries, focusSessionId]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container || !autoFollow) {
      return;
    }
    scrollToBottom("smooth");
  }, [messages.length, status, autoFollow]);

  useEffect(() => {
    if (!autoFollow) {
      return;
    }
    const hasLiveWork = hydratedEntries.some((entry) => entry.status === "active" || entry.live_status === "active");
    if (!hasLiveWork) {
      return;
    }
    const container = scrollRef.current;
    if (!container || !isNearBottom(container)) {
      return;
    }
    scrollToBottom("smooth");
  }, [autoFollow, hydratedEntries]);

  useEffect(() => {
    const hasLiveWork = hydratedEntries.some((entry) => entry.status === "active" || entry.live_status === "active");
    if (!hasLiveWork) {
      return;
    }
    const interval = window.setInterval(() => {
      setLiveRefreshTick((value) => value + 1);
    }, LIVE_REFRESH_MS);
    return () => window.clearInterval(interval);
  }, [hydratedEntries]);

  const mergedItems = useMemo(() => {
    const remote = buildRemoteFeedItems([...hydratedEntries].reverse());
    const local = buildLocalFeedMessages(messages, currentSessionId || activeSessionId);
    return [...remote, ...local]
      .filter((item) => {
        if (filterMode === "all") return true;
        if (filterMode === "messages") return item.kind === "message";
        if (filterMode === "heartbeats") return item.kind === "heartbeat";
        if (filterMode === "errors") {
          if (item.kind === "message") return /error|failed|warning|blocked/i.test(item.message.content);
          return item.entry.status === "failed" || item.entry.event_previews.some((preview) => preview.event_type === "error");
        }
        if (filterMode === "work") {
          return item.kind === "child_run" || item.kind === "heartbeat";
        }
        return true;
      })
      .sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
  }, [hydratedEntries, messages, currentSessionId, activeSessionId, filterMode]);

  const groupedItems = useMemo(() => {
    const groups: Array<{ label: string; blocks: TimelineBlock[] }> = [];
    let currentLabel = "";
    for (const item of mergedItems) {
      const label = formatDayLabel(item.timestamp);
      if (label !== currentLabel) {
        currentLabel = label;
        groups.push({ label, blocks: [] });
      }
      const currentBlocks = groups[groups.length - 1].blocks;
      if (isChildRunItem(item) && item.entry.parent_session_id) {
        const parentBlockIndex = currentBlocks.findLastIndex(
          (block) =>
            block.kind === "item" &&
            canAnchorChildRuns(block.anchorItem) &&
            block.anchorItem.sessionId === item.entry.parent_session_id,
        );
        if (parentBlockIndex >= 0) {
          const parentBlock = currentBlocks[parentBlockIndex];
          if (parentBlock.kind === "item") {
            parentBlock.childRuns.push(item);
          }
          continue;
        }
      }
      currentBlocks.push({ kind: "item", anchorItem: item, childRuns: [] });
    }
    return groups.map((group) => {
      const compressedBlocks: TimelineBlock[] = [];
      let pendingRoutine: ItemTimelineBlock[] = [];
      const flushRoutine = () => {
        if (pendingRoutine.length === 0) {
          return;
        }
        if (pendingRoutine.length === 1) {
          compressedBlocks.push(pendingRoutine[0]);
        } else {
          compressedBlocks.push({
            kind: "routine_group",
            id: `routine:${pendingRoutine[0].anchorItem.id}:${pendingRoutine.at(-1)?.anchorItem.id}`,
            items: pendingRoutine.map((block) => ({
              anchorItem: block.anchorItem as FeedHeartbeat,
              childRuns: block.childRuns,
            })),
          });
        }
        pendingRoutine = [];
      };

      for (const block of group.blocks) {
        if (block.kind !== "item") {
          flushRoutine();
          compressedBlocks.push(block);
          continue;
        }
        if (isRoutineHeartbeatBlock(block, !!deferredSearch.trim(), filterMode)) {
          pendingRoutine.push(block);
          continue;
        }
        flushRoutine();
        compressedBlocks.push(block);
      }
      flushRoutine();
      return { ...group, blocks: compressedBlocks };
    });
  }, [mergedItems, deferredSearch, filterMode]);

  const filterCounts = useMemo(() => {
    const counts: Record<FilterMode, number> = {
      all: hydratedEntries.length + messages.length,
      messages: [...hydratedEntries.filter((entry) => entry.entry_type === "message"), ...messages].length,
      work: hydratedEntries.filter((entry) => entry.entry_type === "heartbeat" || entry.entry_type === "child_run").length,
      errors: hydratedEntries.filter((entry) => entry.status === "failed" || entry.event_previews.some((preview) => preview.event_type === "error")).length,
      heartbeats: hydratedEntries.filter((entry) => entry.entry_type === "heartbeat").length,
    };
    return counts;
  }, [hydratedEntries, messages]);

  const matchedIds = useMemo(() => new Set(searchMatches.map((item) => item.entry_id)), [searchMatches]);
  const activeSearchMatch = useMemo(
    () => searchMatches.findIndex((item) => item.entry_id === activeSearchMatchId),
    [activeSearchMatchId, searchMatches],
  );
  const activeMatchId = activeSearchMatchId && searchMatches.some((item) => item.entry_id === activeSearchMatchId)
    ? activeSearchMatchId
    : searchMatches[0]?.entry_id ?? null;

  useEffect(() => {
    if (!deferredSearch.trim()) {
      setActiveSearchMatchId(null);
      return;
    }

    if (searchMatches.length === 0) {
      return;
    }
    if (!activeSearchMatchId || !searchMatches.some((item) => item.entry_id === activeSearchMatchId)) {
      setActiveSearchMatchId(searchMatches[0]?.entry_id ?? null);
    }
  }, [deferredSearch, searchMatches, activeSearchMatchId]);

  useEffect(() => {
    if (!activeMatchId) {
      return;
    }
    const loaded = mergedItems.some((item) => item.id === activeMatchId);
    if (!loaded && anchorEntryId !== activeMatchId) {
      setAnchorEntryId(activeMatchId);
      return;
    }
    const timeout = window.setTimeout(() => {
      const node = document.querySelector<HTMLElement>(`[data-stream-item-id="${activeMatchId}"]`);
      node?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timeout);
  }, [activeMatchId, mergedItems, anchorEntryId]);

  const handleSessionJump = (sessionId: string | null) => {
    onSelectSession(sessionId);
    setFocusSessionId(sessionId);
    setAnchorEntryId(null);
    setAutoFollow(false);
  };

  const toggleExpanded = (entryId: string) => {
    setExpandedEntryIds((current) => ({
      ...current,
      [entryId]: !current[entryId],
    }));
  };

  const toggleRoutineGroup = (groupId: string) => {
    setExpandedRoutineGroupIds((current) => ({
      ...current,
      [groupId]: !current[groupId],
    }));
  };

  const visibleSearchMatches = useMemo(() => {
    if (searchMatches.length === 0) {
      return [];
    }
    if (activeSearchMatch < 0) {
      return searchMatches.slice(0, 5);
    }
    const start = Math.max(activeSearchMatch - 2, 0);
    const end = Math.min(start + 5, searchMatches.length);
    return searchMatches.slice(Math.max(end - 5, 0), end);
  }, [searchMatches, activeSearchMatch]);

  const jumpToSearchMatch = (direction: 1 | -1) => {
    if (searchMatches.length === 0) {
      return;
    }
    const currentIndex = searchMatches.findIndex((item) => item.entry_id === activeMatchId);
    const fallbackIndex = 0;
    const resolvedIndex = currentIndex >= 0 ? currentIndex : fallbackIndex;

    const nextIndex = resolvedIndex + direction;
    if (nextIndex < 0) {
      setActiveSearchMatchId(searchMatches.at(-1)?.entry_id ?? null);
      setAnchorEntryId(searchMatches.at(-1)?.entry_id ?? null);
      setAutoFollow(false);
      return;
    }
    if (nextIndex >= searchMatches.length) {
      setActiveSearchMatchId(searchMatches[0]?.entry_id ?? null);
      setAnchorEntryId(searchMatches[0]?.entry_id ?? null);
      setAutoFollow(false);
      return;
    }
    setActiveSearchMatchId(searchMatches[nextIndex].entry_id);
    setAnchorEntryId(searchMatches[nextIndex].entry_id);
    setAutoFollow(false);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <div className="flex flex-wrap items-center gap-2">
          <SessionDropdown
            activeSessionId={activeSessionId}
            onSelectSession={handleSessionJump}
            onNewSession={onNewSession}
            projectId={PROJECT_ID}
            refreshTrigger={sidebarRefreshTrigger}
          />
          <div className="relative min-w-[18rem] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              id={searchInputId}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setAnchorEntryId(null);
              }}
              placeholder="Search Jenny's history, task IDs, files, agents..."
              className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-sm text-slate-700 outline-none transition focus:border-sky-300 focus:bg-white dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-700"
            />
          </div>
          <TimeRangeDropdown value={timeRange} onChange={setTimeRange} />
          <button
            type="button"
            onClick={() => {
              setAutoFollow((value) => {
                const next = !value;
                if (next) {
                  window.setTimeout(() => {
                    scrollToBottom("smooth");
                  }, 0);
                }
                return next;
              });
            }}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium transition",
              autoFollow
                ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-800"
                : "bg-slate-100 text-slate-600 ring-1 ring-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-700",
            )}
          >
            <Radio className="h-4 w-4" />
            {autoFollow ? "Auto-follow on" : "Auto-follow off"}
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {([
            ["all", "All"],
            ["messages", "Messages"],
            ["work", "Work"],
            ["errors", "Errors"],
            ["heartbeats", "Heartbeats"],
          ] as Array<[FilterMode, string]>).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setFilterMode(value)}
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition",
                filterMode === value
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800",
              )}
            >
              {label}
              <span className="opacity-70">{filterCounts[value]}</span>
            </button>
          ))}
        </div>
        {deferredSearch.trim() && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
            <span>
              {matchCount === 0
                ? `No matches for "${deferredSearch.trim()}"`
                : `${Math.max(activeSearchMatch, 0) + 1} of ${matchCount} matches for "${deferredSearch.trim()}"`}
            </span>
            {matchCount > 0 && (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => jumpToSearchMatch(-1)}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-white dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  <ArrowUp className="h-3.5 w-3.5" />
                  Prev match
                </button>
                <button
                  type="button"
                  onClick={() => jumpToSearchMatch(1)}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-white dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  <ArrowDown className="h-3.5 w-3.5" />
                  Next match
                </button>
              </div>
            )}
          </div>
        )}
        {deferredSearch.trim() && visibleSearchMatches.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {visibleSearchMatches.map((match) => (
              <button
                key={match.entry_id}
                type="button"
                onClick={() => {
                  setActiveSearchMatchId(match.entry_id);
                  setAnchorEntryId(match.entry_id);
                  setAutoFollow(false);
                }}
                className={cn(
                  "max-w-full rounded-2xl border px-3 py-2 text-left text-xs transition",
                  match.entry_id === activeMatchId
                    ? "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-100"
                    : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:bg-slate-900",
                )}
              >
                <div className="font-semibold uppercase tracking-[0.14em] text-[10px] opacity-70">
                  {formatTimeLabel(new Date(match.timestamp))} · {match.entry_type}
                </div>
                <HighlightedText text={shortenText(match.snippet, 90)} className="mt-1 block" />
              </button>
            ))}
          </div>
        )}
      </div>

      <div ref={scrollRef} data-testid="stream-scroll-container" className="flex-1 overflow-y-auto px-4 py-4">
        {(error || chatError) && (
          <div className="mb-4 flex items-center gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-300">
            <AlertCircle className="h-4 w-4" />
            {error || chatError}
          </div>
        )}

        {loading && entries.length === 0 ? (
          <div className="flex items-center justify-center py-20 text-slate-400">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : groupedItems.length === 0 ? (
          <div className="py-20 text-center text-slate-500 dark:text-slate-400">
            No stream entries yet.
          </div>
        ) : (
          <div className="mx-auto max-w-4xl">
            {groupedItems.map((group) => (
              <div key={group.label}>
                <DateDivider label={group.label} />
                <div className="space-y-3">
                  {group.blocks.map((block) => {
                    if (block.kind === "routine_group") {
                      return (
                        <RoutineHeartbeatGroup
                          key={block.id}
                          block={block}
                          expanded={!!expandedRoutineGroupIds[block.id]}
                          onToggle={() => toggleRoutineGroup(block.id)}
                          activeSessionId={activeSessionId}
                          expandedEntryIds={expandedEntryIds}
                          onToggleEntry={toggleExpanded}
                        />
                      );
                    }

                    const item = block.anchorItem;
                    const selected = !!item.sessionId && item.sessionId === activeSessionId;
                    const matched = matchedIds.has(item.id);
                    const activeMatched = activeMatchId === item.id;
                    if (item.kind === "message") {
                      return (
                        <div
                          key={item.id}
                          data-session-anchor={item.sessionId ?? undefined}
                          data-testid="stream-item"
                          data-stream-item-id={item.id}
                          data-timestamp={item.timestamp.toISOString()}
                          className={cn(
                            "flex items-start gap-3",
                            selected && "rounded-2xl bg-sky-50/40 px-2 py-1 dark:bg-sky-950/10",
                            matched && "rounded-2xl px-2 py-1 ring-1 ring-amber-200 dark:ring-amber-800",
                            activeMatched && "ring-2 ring-amber-400 dark:ring-amber-500",
                          )}
                        >
                          <TimelineTimestamp timestamp={item.timestamp} />
                          <div className="min-w-0 flex-1">
                            <MessageBubble
                              message={item.message}
                              isStreaming={status !== "idle" && status !== "error"}
                              canEdit={false}
                              canRegenerate={false}
                            />
                            {block.childRuns.length > 0 && (
                              <ChildRunStack
                                childRuns={block.childRuns}
                                activeSessionId={activeSessionId}
                                expandedEntryIds={expandedEntryIds}
                                onToggle={toggleExpanded}
                                matchedIds={matchedIds}
                                activeMatchId={activeMatchId}
                              />
                            )}
                          </div>
                        </div>
                      );
                    }
                    if (item.kind === "child_run") {
                      return (
                        <div
                          key={item.id}
                          data-session-anchor={item.sessionId}
                          data-testid="stream-item"
                          data-stream-item-id={item.id}
                          data-timestamp={item.timestamp.toISOString()}
                          className={cn(
                            "flex items-start gap-3 rounded-2xl",
                            matched && "px-2 py-1 ring-1 ring-amber-200 dark:ring-amber-800",
                            activeMatched && "ring-2 ring-amber-400 dark:ring-amber-500",
                          )}
                        >
                          <TimelineTimestamp timestamp={item.timestamp} />
                          <div className="min-w-0 flex-1">
                            <ChildRunCard
                              entry={item.entry}
                              selected={selected}
                              expanded={!!expandedEntryIds[item.id]}
                              onToggle={() => toggleExpanded(item.id)}
                            />
                          </div>
                        </div>
                      );
                    }
                    return (
                      <div
                        key={item.id}
                        data-session-anchor={item.sessionId}
                        data-testid="stream-item"
                        data-stream-item-id={item.id}
                        data-timestamp={item.timestamp.toISOString()}
                        className={cn(
                          "flex items-start gap-3 rounded-2xl",
                          matched && "px-2 py-1 ring-1 ring-amber-200 dark:ring-amber-800",
                          activeMatched && "ring-2 ring-amber-400 dark:ring-amber-500",
                        )}
                      >
                        <TimelineTimestamp timestamp={item.timestamp} />
                        <div className="min-w-0 flex-1">
                          <HeartbeatCard
                            entry={item.entry}
                            selected={selected}
                            expanded={!!expandedEntryIds[item.id]}
                            onToggle={() => toggleExpanded(item.id)}
                          />
                          {block.childRuns.length > 0 && (
                            <ChildRunStack
                              childRuns={block.childRuns}
                              activeSessionId={activeSessionId}
                              expandedEntryIds={expandedEntryIds}
                              onToggle={toggleExpanded}
                              matchedIds={matchedIds}
                              activeMatchId={activeMatchId}
                            />
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}

            {total > entries.length && !deferredSearch.trim() && (
              <div className="flex justify-center pt-6">
                <button
                  onClick={() => setPage((value) => value + 1)}
                  className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600 transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  Load older entries
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-950/95">
        <div className="mx-auto max-w-4xl">
          <div className="mb-2 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
            <span className="inline-flex items-center gap-1">
              <Sparkles className="h-3.5 w-3.5" />
              Composer is attached to {activeSessionId ? `session ${activeSessionId.slice(0, 8)}` : "a new thread"}
            </span>
            {status !== "idle" && (
              <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-300">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Jenny is responding
              </span>
            )}
          </div>
          <MessageInput
            onSend={sendMessage}
            onCancel={cancelStream}
            status={status}
            voiceWsUrl={getWsUrl("/api/voice/ws?user_id=agent_hub_user&app=agent-hub&mode=transcribe")}
            ttsBaseUrl={getApiBaseUrl() || window.location.origin}
            preferencesEndpoint={apiConfig.preferencesEndpoint}
            fetchFn={fetchApi}
          />
        </div>
      </div>
    </div>
  );
}
