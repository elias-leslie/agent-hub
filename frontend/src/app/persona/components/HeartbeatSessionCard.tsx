"use client";

import { useState, useCallback } from "react";
import {
  ChevronRight,
  Wrench,
  Brain,
  MessageSquare,
  AlertCircle,
  Loader2,
  Zap,
  Clock,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { cn } from "@/lib/utils";
import { fetchApi } from "@/lib/api-config";
import { MarkdownContent } from "@agent-hub/chat-ui";
import { fixSpacing } from "../utils/text";

interface EventPreview {
  event_type: string;
  tool_name: string | null;
  content_preview: string | null;
}

interface SessionEvent {
  id: string;
  turn: number;
  sequence: number;
  event_type: string;
  role: string | null;
  content: string | null;
  tool_name: string | null;
  tool_input: Record<string, unknown> | null;
  tool_output: Record<string, unknown> | null;
  tokens: number | null;
  duration_ms: number | null;
  created_at: string;
}

interface HeartbeatSessionCardProps {
  id: string;
  summary: string | null;
  status: string;
  messageCount: number;
  createdAt: string;
  eventsPreview: EventPreview[];
}

/* ── Tool Category System ─────────────────────────── */

const CATEGORY_STYLES = {
  memory: {
    dot: "bg-violet-400 ring-violet-500/20",
    badge: "bg-violet-500/10 border-violet-500/20 text-violet-400",
  },
  schedule: {
    dot: "bg-blue-400 ring-blue-500/20",
    badge: "bg-blue-500/10 border-blue-500/20 text-blue-400",
  },
  system: {
    dot: "bg-amber-400 ring-amber-500/20",
    badge: "bg-amber-500/10 border-amber-500/20 text-amber-400",
  },
  file: {
    dot: "bg-emerald-400 ring-emerald-500/20",
    badge: "bg-emerald-500/10 border-emerald-500/20 text-emerald-400",
  },
  search: {
    dot: "bg-cyan-400 ring-cyan-500/20",
    badge: "bg-cyan-500/10 border-cyan-500/20 text-cyan-400",
  },
  default: {
    dot: "bg-slate-400 ring-slate-500/20",
    badge: "bg-slate-500/10 border-slate-500/20 text-slate-400",
  },
} as const;

type ToolCategory = keyof typeof CATEGORY_STYLES;

function getToolCategory(toolName: string | null): ToolCategory {
  if (!toolName) return "default";
  const name = toolName.toLowerCase();
  if (name.includes("memory") || name.includes("journal")) return "memory";
  if (name.includes("schedule") || name.includes("cron")) return "schedule";
  if (name === "bash" || name.includes("service") || name.includes("health"))
    return "system";
  if (["read", "write", "edit", "glob"].includes(name)) return "file";
  if (["grep", "websearch", "webfetch"].includes(name)) return "search";
  return "default";
}

/* ── Sub-components ───────────────────────────────── */

function CollapsibleText({
  content,
  maxLength = 300,
  className,
}: {
  content: string;
  maxLength?: number;
  className?: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const needsTruncation = content.length > maxLength;
  const display = isOpen ? content : content.slice(0, maxLength);

  return (
    <div>
      <span className={cn("whitespace-pre-wrap break-all", className)}>
        {display}
        {needsTruncation && !isOpen && "\u2026"}
      </span>
      {needsTruncation && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            setIsOpen(!isOpen);
          }}
          className="ml-1 text-[9px] text-amber-500/70 hover:text-amber-400"
        >
          {isOpen ? "\u25be less" : "\u25b8 more"}
        </button>
      )}
    </div>
  );
}

function DurationBadge({ ms }: { ms: number }) {
  const label = ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
  return (
    <span className="inline-flex items-center gap-0.5 text-[9px] font-mono text-slate-500">
      <Clock className="w-2.5 h-2.5" />
      {label}
    </span>
  );
}

/* ── Expanded Event (timeline-style) ──────────────── */

function ExpandedEvent({ event }: { event: SessionEvent }) {
  const [open, setOpen] = useState(false);

  /* ─── Thinking ─── */
  if (event.event_type === "thinking") {
    const wordCount = event.content ? event.content.split(/\s+/).length : 0;
    return (
      <div className="relative pl-5 py-1">
        <div className="absolute left-0 top-[10px] w-2 h-2 rounded-full ring-2 bg-violet-400 ring-violet-500/20" />
        <div className="absolute left-[3px] top-[18px] bottom-0 w-px bg-slate-700/20" />

        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 w-full text-left"
        >
          <Brain className="w-3 h-3 text-violet-400 flex-shrink-0" />
          <span className="text-[10px] font-medium text-violet-400">
            Thinking
          </span>
          <ChevronRight
            className={cn(
              "w-2.5 h-2.5 text-violet-400/40 transition-transform duration-150",
              open && "rotate-90",
            )}
          />
          <span className="ml-auto flex items-center gap-2 text-[9px] text-slate-500">
            {wordCount > 0 && <span>{wordCount} words</span>}
            {event.tokens != null && (
              <span className="font-mono">{event.tokens}t</span>
            )}
          </span>
        </button>
        {open && event.content && (
          <div className="mt-1.5 ml-5 rounded-md bg-gradient-to-br from-violet-500/5 to-transparent border border-violet-500/10 p-2.5">
            <p className="text-[11px] text-slate-400 whitespace-pre-wrap leading-relaxed">
              {event.content}
            </p>
          </div>
        )}
      </div>
    );
  }

  /* ─── Tool Use ─── */
  if (event.event_type === "tool_use") {
    const input = event.tool_input as Record<string, unknown> | null;
    const isBash = event.tool_name === "Bash";
    const description =
      isBash && input?.description ? String(input.description) : null;
    const command = isBash && input?.command ? String(input.command) : null;
    const category = getToolCategory(event.tool_name);
    const catStyle = CATEGORY_STYLES[category];

    return (
      <div className="relative pl-5 py-1">
        <div
          className={cn(
            "absolute left-0 top-[10px] w-2 h-2 rounded-full ring-2",
            catStyle.dot,
          )}
        />
        <div className="absolute left-[3px] top-[18px] bottom-0 w-px bg-slate-700/20" />

        <div className="flex items-center gap-2 flex-wrap">
          <Wrench className="w-3 h-3 text-amber-500 flex-shrink-0" />
          <span
            className={cn(
              "text-[9px] font-bold font-mono uppercase tracking-wider px-1.5 py-0.5 rounded border",
              catStyle.badge,
            )}
          >
            {category !== "default" ? category : "tool"}
          </span>
          <span className="text-[10px] font-semibold font-mono text-slate-300">
            {event.tool_name || "tool"}
          </span>
          {description && (
            <span className="text-[9px] text-slate-500 italic truncate max-w-[200px]">
              {description}
            </span>
          )}
          {event.duration_ms != null && (
            <span className="ml-auto flex-shrink-0">
              <DurationBadge ms={event.duration_ms} />
            </span>
          )}
        </div>
        {command ? (
          <div className="mt-1 ml-5">
            <CollapsibleText
              content={command}
              maxLength={200}
              className="text-[10px] text-slate-500 font-mono"
            />
          </div>
        ) : input ? (
          <div className="mt-1 ml-5">
            <CollapsibleText
              content={JSON.stringify(input, null, 2)}
              maxLength={200}
              className="text-[10px] text-slate-500 font-mono"
            />
          </div>
        ) : null}
      </div>
    );
  }

  /* ─── Tool Result ─── */
  if (event.event_type === "tool_result") {
    const resultContent =
      event.content ||
      (event.tool_output as Record<string, unknown>)?.content?.toString() ||
      "";
    if (!resultContent) return null;

    return (
      <div className="relative pl-5 py-0.5">
        <div className="absolute left-[2px] top-[8px] w-1 h-1 rounded-full bg-slate-600" />
        <div className="absolute left-[3px] top-[12px] bottom-0 w-px bg-slate-700/20" />

        <div className="ml-5 rounded bg-slate-800/40 border border-slate-700/30 px-2 py-1.5">
          <CollapsibleText
            content={resultContent}
            maxLength={300}
            className="text-[9px] text-slate-500 font-mono"
          />
        </div>
      </div>
    );
  }

  /* ─── Assistant Message ─── */
  if (event.event_type === "assistant_message") {
    return (
      <div className="relative pl-5 py-1">
        <div className="absolute left-0 top-[10px] w-2 h-2 rounded-full ring-2 bg-sky-400 ring-sky-500/20" />
        <div className="absolute left-[3px] top-[18px] bottom-0 w-px bg-slate-700/20" />

        <div className="flex items-center gap-2 mb-1">
          <MessageSquare className="w-3 h-3 text-sky-400 flex-shrink-0" />
          <span className="text-[10px] font-medium text-sky-400">
            Response
          </span>
        </div>
        {event.content && (
          <div className="ml-5">
            <MarkdownContent
              content={event.content}
              className="text-[11px] leading-relaxed [&_p]:my-0.5 [&_code]:text-[10px]"
            />
          </div>
        )}
      </div>
    );
  }

  /* ─── Error ─── */
  if (event.event_type === "error") {
    return (
      <div className="relative pl-5 py-1">
        <div className="absolute left-0 top-[10px] w-2 h-2 rounded-full ring-2 bg-red-400 ring-red-500/20" />
        <div className="absolute left-[3px] top-[18px] bottom-0 w-px bg-slate-700/20" />

        <div className="flex items-start gap-2">
          <AlertCircle className="w-3 h-3 text-red-400 mt-0.5 flex-shrink-0" />
          <p className="text-[11px] text-red-400 font-mono break-words whitespace-pre-wrap">
            {event.content}
          </p>
        </div>
      </div>
    );
  }

  /* ─── Fallback ─── */
  if (event.content) {
    return (
      <div className="relative pl-5 py-0.5">
        <div className="absolute left-[2px] top-[6px] w-1 h-1 rounded-full bg-slate-600" />
        <div className="absolute left-[3px] top-[10px] bottom-0 w-px bg-slate-700/20" />
        <span className="text-[10px] text-slate-500 break-words">
          {event.event_type}: {event.content}
        </span>
      </div>
    );
  }

  return null;
}

/* ── Main Component ───────────────────────────────── */

export function HeartbeatSessionCard({
  id,
  summary,
  status,
  messageCount,
  createdAt,
  eventsPreview,
}: HeartbeatSessionCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [events, setEvents] = useState<SessionEvent[] | null>(null);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsError, setEventsError] = useState<string | null>(null);

  const toolCount = eventsPreview.filter(
    (e) => e.event_type === "tool_use",
  ).length;

  const handleToggle = useCallback(async () => {
    if (!expanded && events === null && !eventsError) {
      setEventsLoading(true);
      setEventsError(null);
      try {
        const res = await fetchApi(
          `/api/sessions/${id}/events?page_size=200`,
        );
        if (res.ok) {
          const data = await res.json();
          setEvents(data.events || []);
        } else {
          setEventsError("Failed to load events");
        }
      } catch {
        setEventsError("Failed to load events");
      } finally {
        setEventsLoading(false);
      }
    }
    setExpanded(!expanded);
  }, [expanded, events, eventsError, id]);

  const timeAgo = formatDistanceToNow(new Date(createdAt), {
    addSuffix: true,
  });
  const statusLabel = summary?.startsWith("HEARTBEAT_ACTION")
    ? "ACTION"
    : summary?.startsWith("HEARTBEAT_OK")
      ? "OK"
      : null;

  const toolCategories = [
    ...new Set(
      eventsPreview
        .filter((e) => e.event_type === "tool_use" && e.tool_name)
        .map((e) => getToolCategory(e.tool_name)),
    ),
  ];

  return (
    <div
      className={cn(
        "group rounded-lg border transition-all duration-200",
        "border-amber-200/30 dark:border-amber-800/30",
        "bg-gradient-to-r from-amber-50/40 via-transparent to-transparent",
        "dark:from-amber-950/15 dark:via-transparent dark:to-transparent",
        expanded && "border-amber-300/50 dark:border-amber-700/40",
      )}
    >
      {/* Collapsed header */}
      <button
        onClick={handleToggle}
        className="w-full flex items-center gap-3 px-3 py-2.5 text-left"
      >
        <div className="flex-shrink-0 relative">
          <div className="w-2 h-2 rounded-full bg-amber-400 dark:bg-amber-500" />
          {status === "active" && (
            <div className="absolute inset-0 w-2 h-2 rounded-full bg-amber-400 animate-ping opacity-40" />
          )}
        </div>

        <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500 flex-shrink-0 w-20 tabular-nums">
          {timeAgo}
        </span>

        <span className="flex-1 text-xs text-slate-600 dark:text-slate-300 truncate">
          {summary
            ? fixSpacing(
                summary
                  .replace(/^HEARTBEAT_(OK|ACTION)\s*[—–-]?\s*/i, "")
                  .trim(),
              ) || "Heartbeat completed"
            : "Heartbeat check"}
        </span>

        <div className="flex items-center gap-2 flex-shrink-0">
          {statusLabel && (
            <span
              className={cn(
                "text-[9px] font-bold font-mono px-1.5 py-0.5 rounded",
                statusLabel === "ACTION"
                  ? "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300"
                  : "bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400",
              )}
            >
              {statusLabel}
            </span>
          )}
          {messageCount > 0 && (
            <span className="text-[9px] font-mono text-slate-400 dark:text-slate-500">
              {messageCount}msg
            </span>
          )}
          {toolCategories.length > 0 && (
            <div className="flex items-center gap-1">
              {toolCategories.slice(0, 3).map((cat) => (
                <span
                  key={cat}
                  className={cn(
                    "w-1.5 h-1.5 rounded-full",
                    CATEGORY_STYLES[cat].dot.split(" ")[0],
                  )}
                />
              ))}
              {toolCount > 0 && (
                <span className="text-[9px] font-mono text-amber-600 dark:text-amber-400">
                  {toolCount}
                </span>
              )}
            </div>
          )}
          <ChevronRight
            className={cn(
              "w-3.5 h-3.5 text-slate-400 transition-transform duration-200",
              expanded && "rotate-90",
            )}
          />
        </div>
      </button>

      {/* Expanded events */}
      {expanded && (
        <div className="px-3 pb-3 border-t border-amber-200/20 dark:border-amber-800/20">
          {eventsLoading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="w-4 h-4 animate-spin text-amber-400" />
            </div>
          ) : eventsError ? (
            <div className="flex items-center justify-center gap-2 py-3">
              <AlertCircle className="w-3.5 h-3.5 text-red-400" />
              <p className="text-[10px] text-red-400">{eventsError}</p>
              <button
                onClick={async (e) => {
                  e.stopPropagation();
                  setEventsError(null);
                  setEventsLoading(true);
                  try {
                    const res = await fetchApi(
                      `/api/sessions/${id}/events?page_size=200`,
                    );
                    if (res.ok) {
                      const data = await res.json();
                      setEvents(data.events || []);
                    } else {
                      setEventsError("Failed to load events");
                    }
                  } catch {
                    setEventsError("Failed to load events");
                  } finally {
                    setEventsLoading(false);
                  }
                }}
                className="text-[10px] text-amber-500 hover:text-amber-400 underline"
              >
                Retry
              </button>
            </div>
          ) : events && events.length > 0 ? (
            <div className="mt-2 max-h-[500px] overflow-y-auto pr-1">
              {events
                .filter((e) =>
                  [
                    "thinking",
                    "tool_use",
                    "tool_result",
                    "assistant_message",
                    "error",
                  ].includes(e.event_type),
                )
                .map((event) => (
                  <ExpandedEvent key={event.id} event={event} />
                ))}
            </div>
          ) : (
            <p className="text-[10px] text-slate-500 py-3 text-center">
              No events recorded
            </p>
          )}
        </div>
      )}
    </div>
  );
}
