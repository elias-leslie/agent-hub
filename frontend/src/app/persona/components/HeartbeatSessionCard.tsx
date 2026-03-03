"use client";

import { useState, useCallback } from "react";
import { ChevronRight, AlertCircle, Loader2 } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { cn } from "@/lib/utils";
import { fetchApi } from "@/lib/api-config";
import { fixSpacing } from "../utils/text";
import {
  HeartbeatSessionCardProps,
  SessionEvent,
  CATEGORY_STYLES,
  getToolCategory,
} from "./HeartbeatSessionCardTypes";
import { ExpandedEvent } from "./HeartbeatExpandedEvent";

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

  const loadEvents = useCallback(async () => {
    setEventsLoading(true);
    setEventsError(null);
    try {
      const res = await fetchApi(`/api/sessions/${id}/events?page_size=200`);
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
  }, [id]);

  const handleToggle = useCallback(async () => {
    if (!expanded && events === null && !eventsError) {
      await loadEvents();
    }
    setExpanded(!expanded);
  }, [expanded, events, eventsError, loadEvents]);

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
        className="w-full flex items-start gap-3 px-3 py-2.5 text-left"
      >
        <div className="flex-shrink-0 relative mt-1">
          <div className="w-2 h-2 rounded-full bg-amber-400 dark:bg-amber-500" />
          {status === "active" && (
            <div className="absolute inset-0 w-2 h-2 rounded-full bg-amber-400 animate-ping opacity-40" />
          )}
        </div>

        <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500 flex-shrink-0 w-20 tabular-nums mt-0.5">
          {timeAgo}
        </span>

        <span className="flex-1 text-xs text-slate-600 dark:text-slate-300 line-clamp-2">
          {summary
            ? fixSpacing(
                summary
                  .replace(/^HEARTBEAT_(OK|ACTION)\s*[—–-]?\s*/i, "")
                  .trim(),
              ) || "Heartbeat completed"
            : "Heartbeat check"}
        </span>

        <div className="flex items-center gap-2 flex-shrink-0 mt-0.5">
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
                  await loadEvents();
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
