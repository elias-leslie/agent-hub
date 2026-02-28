"use client";

import { useState, useCallback } from "react";
import { ChevronRight, Wrench, Brain, MessageSquare, AlertCircle, Loader2, Zap } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { cn } from "@/lib/utils";
import { fetchApi } from "@/lib/api-config";

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

function EventIcon({ type }: { type: string }) {
  switch (type) {
    case "tool_use":
    case "tool_result":
      return <Wrench className="w-3 h-3 text-amber-500" />;
    case "thinking":
      return <Brain className="w-3 h-3 text-violet-400" />;
    case "assistant_message":
      return <MessageSquare className="w-3 h-3 text-sky-400" />;
    case "error":
      return <AlertCircle className="w-3 h-3 text-red-400" />;
    default:
      return <Zap className="w-3 h-3 text-slate-400" />;
  }
}

function ExpandedEvent({ event }: { event: SessionEvent }) {
  const [thinkingOpen, setThinkingOpen] = useState(false);

  if (event.event_type === "thinking") {
    return (
      <div className="group">
        <button
          onClick={() => setThinkingOpen(!thinkingOpen)}
          className="flex items-center gap-2 w-full text-left py-1"
        >
          <EventIcon type="thinking" />
          <span className="text-[10px] font-medium text-violet-400">Thinking</span>
          <ChevronRight
            className={cn(
              "w-2.5 h-2.5 text-slate-500 transition-transform",
              thinkingOpen && "rotate-90",
            )}
          />
          {event.tokens && (
            <span className="text-[9px] font-mono text-slate-500 ml-auto">{event.tokens}t</span>
          )}
        </button>
        {thinkingOpen && event.content && (
          <div className="ml-5 pl-2 border-l border-violet-900/30 mb-1">
            <p className="text-[11px] text-slate-400 whitespace-pre-wrap leading-relaxed">
              {event.content}
            </p>
          </div>
        )}
      </div>
    );
  }

  if (event.event_type === "tool_use") {
    return (
      <div className="flex items-start gap-2 py-1">
        <EventIcon type="tool_use" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold font-mono text-amber-400">
              {event.tool_name || "tool"}
            </span>
            {event.duration_ms != null && (
              <span className="text-[9px] font-mono text-slate-500">{event.duration_ms}ms</span>
            )}
          </div>
          {event.tool_input && (
            <p className="text-[10px] text-slate-500 font-mono break-all mt-0.5">
              {JSON.stringify(event.tool_input)}
            </p>
          )}
        </div>
      </div>
    );
  }

  if (event.event_type === "tool_result") {
    return (
      <div className="flex items-start gap-2 py-0.5 ml-5">
        <span className="text-[9px] text-slate-500 font-mono break-all whitespace-pre-wrap">
          {event.content || ""}
        </span>
      </div>
    );
  }

  if (event.event_type === "assistant_message") {
    return (
      <div className="flex items-start gap-2 py-1">
        <EventIcon type="assistant_message" />
        <p className="text-[11px] text-slate-300 whitespace-pre-wrap leading-relaxed flex-1 break-words">
          {event.content}
        </p>
      </div>
    );
  }

  if (event.event_type === "error") {
    return (
      <div className="flex items-start gap-2 py-1">
        <EventIcon type="error" />
        <p className="text-[11px] text-red-400 font-mono break-words whitespace-pre-wrap">{event.content}</p>
      </div>
    );
  }

  // Generic fallback for other event types
  if (event.content) {
    return (
      <div className="flex items-start gap-2 py-0.5">
        <EventIcon type={event.event_type} />
        <span className="text-[10px] text-slate-500 break-words">
          {event.event_type}: {event.content}
        </span>
      </div>
    );
  }

  return null;
}

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

  const toolCount = eventsPreview.filter(
    (e) => e.event_type === "tool_use",
  ).length;

  const handleToggle = useCallback(async () => {
    if (!expanded && events === null) {
      setEventsLoading(true);
      try {
        const res = await fetchApi(`/api/sessions/${id}/events?page_size=200`);
        if (res.ok) {
          const data = await res.json();
          setEvents(data.events || []);
        }
      } catch {
        // silently fail
      } finally {
        setEventsLoading(false);
      }
    }
    setExpanded(!expanded);
  }, [expanded, events, id]);

  const timeAgo = formatDistanceToNow(new Date(createdAt), { addSuffix: true });
  const statusLabel = summary?.startsWith("HEARTBEAT_ACTION")
    ? "ACTION"
    : summary?.startsWith("HEARTBEAT_OK")
      ? "OK"
      : null;

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
        {/* Amber pulse indicator */}
        <div className="flex-shrink-0 relative">
          <div className="w-2 h-2 rounded-full bg-amber-400 dark:bg-amber-500" />
          {status === "active" && (
            <div className="absolute inset-0 w-2 h-2 rounded-full bg-amber-400 animate-ping opacity-40" />
          )}
        </div>

        {/* Timestamp */}
        <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500 flex-shrink-0 w-20 tabular-nums">
          {timeAgo}
        </span>

        {/* Summary */}
        <span className="flex-1 text-xs text-slate-600 dark:text-slate-300 truncate">
          {summary
            ? summary
                .replace(/^HEARTBEAT_(OK|ACTION)\s*[—–-]?\s*/i, "")
                .trim() || "Heartbeat completed"
            : "Heartbeat check"}
        </span>

        {/* Badges */}
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
          {toolCount > 0 && (
            <span className="flex items-center gap-0.5 text-[9px] font-mono text-amber-600 dark:text-amber-400">
              <Wrench className="w-2.5 h-2.5" />
              {toolCount}
            </span>
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
          ) : events && events.length > 0 ? (
            <div className="mt-2 space-y-0.5 max-h-[400px] overflow-y-auto">
              {events
                .filter((e) =>
                  ["thinking", "tool_use", "tool_result", "assistant_message", "error"].includes(
                    e.event_type,
                  ),
                )
                .map((event) => (
                  <ExpandedEvent key={event.id} event={event} />
                ))}
            </div>
          ) : (
            <p className="text-[10px] text-slate-500 py-3 text-center">No events recorded</p>
          )}
        </div>
      )}
    </div>
  );
}
