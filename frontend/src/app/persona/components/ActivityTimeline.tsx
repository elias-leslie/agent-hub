"use client";

import { useState, useEffect, useCallback } from "react";
import { MessageSquare, Loader2, Radio, Inbox } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { cn } from "@/lib/utils";
import { fetchApi } from "@/lib/api-config";

import { TimeRangeDropdown, type TimeRange } from "./TimeRangeDropdown";
import { HeartbeatSessionCard } from "./HeartbeatSessionCard";

interface EventPreview {
  event_type: string;
  tool_name: string | null;
  content_preview: string | null;
}

interface ActivitySession {
  id: string;
  session_type: string;
  summary_oneliner: string | null;
  status: string;
  message_count: number;
  created_at: string;
  updated_at: string;
  events_preview: EventPreview[];
}

interface ActivityTimelineProps {
  onSelectChatSession?: (sessionId: string) => void;
}

function SkeletonCard() {
  return (
    <div className="rounded-lg border border-slate-200/50 dark:border-slate-800/50 p-3 animate-pulse">
      <div className="flex items-center gap-3">
        <div className="w-2 h-2 rounded-full bg-slate-200 dark:bg-slate-700" />
        <div className="w-16 h-3 rounded bg-slate-200 dark:bg-slate-700" />
        <div className="flex-1 h-3 rounded bg-slate-200 dark:bg-slate-700" />
        <div className="w-8 h-3 rounded bg-slate-200 dark:bg-slate-700" />
      </div>
    </div>
  );
}

/** Fix missing spaces in concatenated summaries (e.g. "opportunities.Good" → "opportunities. Good") */
function fixSpacing(text: string): string {
  return text
    .replace(/([.!?])([A-Z])/g, "$1 $2")
    .replace(/(\])([A-Z])/g, "$1 $2");
}

function ChatSessionCard({
  session,
  onSelect,
}: {
  session: ActivitySession;
  onSelect?: (id: string) => void;
}) {
  const timeAgo = formatDistanceToNow(new Date(session.created_at), { addSuffix: true });

  return (
    <button
      onClick={() => onSelect?.(session.id)}
      className={cn(
        "w-full rounded-lg border transition-all duration-150 text-left",
        "border-slate-200/50 dark:border-slate-700/50",
        "hover:border-slate-300 dark:hover:border-slate-600",
        "bg-white/50 dark:bg-slate-800/30",
        "hover:bg-white dark:hover:bg-slate-800/60",
        "px-3 py-2.5 group",
      )}
    >
      <div className="flex items-center gap-3">
        {/* Chat indicator */}
        <div className="flex-shrink-0">
          <MessageSquare className="w-3.5 h-3.5 text-sky-400" />
        </div>

        {/* Timestamp */}
        <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500 flex-shrink-0 w-20 tabular-nums">
          {timeAgo}
        </span>

        {/* Summary */}
        <span className="flex-1 text-xs text-slate-600 dark:text-slate-300 truncate">
          {session.summary_oneliner ? fixSpacing(session.summary_oneliner) : "Chat session"}
        </span>

        {/* Message count */}
        <span className="flex items-center gap-1 text-[9px] font-mono text-slate-400 dark:text-slate-500 flex-shrink-0">
          <MessageSquare className="w-2.5 h-2.5" />
          {session.message_count}
        </span>
      </div>
    </button>
  );
}

function DateDivider({ date }: { date: string }) {
  return (
    <div className="flex items-center gap-3 py-2">
      <div className="flex-1 h-px bg-slate-200/60 dark:bg-slate-800/60" />
      <span className="text-[10px] font-mono font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider">
        {date}
      </span>
      <div className="flex-1 h-px bg-slate-200/60 dark:bg-slate-800/60" />
    </div>
  );
}

export function ActivityTimeline({ onSelectChatSession }: ActivityTimelineProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [sessions, setSessions] = useState<ActivitySession[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 50;

  const fetchActivity = useCallback(
    async (pageNum: number, range: TimeRange) => {
      setLoading(true);
      try {
        const res = await fetchApi(
          `/api/persona/activity?time_range=${range}&page=${pageNum}&page_size=${pageSize}`,
        );
        if (res.ok) {
          const data = await res.json();
          const newSessions = data.sessions || [];
          setSessions((prev) => (pageNum > 1 ? [...prev, ...newSessions] : newSessions));
          setTotal(data.total || 0);
        }
      } catch {
        // silently handle
      } finally {
        setLoading(false);
      }
    },
    [pageSize],
  );

  useEffect(() => {
    setPage(1);
    fetchActivity(1, timeRange);
  }, [timeRange, fetchActivity]);

  const handleTimeRangeChange = useCallback((range: TimeRange) => {
    setTimeRange(range);
  }, []);

  const handleLoadMore = useCallback(() => {
    const nextPage = page + 1;
    setPage(nextPage);
    fetchActivity(nextPage, timeRange);
  }, [page, timeRange, fetchActivity]);

  // Group sessions by date for dividers
  const groupedSessions: { date: string; items: ActivitySession[] }[] = [];
  let currentDate = "";
  for (const session of sessions) {
    const date = new Date(session.created_at).toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
    if (date !== currentDate) {
      currentDate = date;
      groupedSessions.push({ date, items: [] });
    }
    groupedSessions[groupedSessions.length - 1].items.push(session);
  }

  const isHeartbeatSession = (s: ActivitySession) =>
    s.session_type === "heartbeat" || s.session_type === "completion";

  return (
    <div className="flex flex-col h-full">
      {/* Timeline header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200/50 dark:border-slate-800/50 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Radio className="w-3.5 h-3.5 text-amber-500" />
          <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
            Activity
          </span>
          {!loading && (
            <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500">
              {total} session{total !== 1 ? "s" : ""}
            </span>
          )}
        </div>
        <TimeRangeDropdown value={timeRange} onChange={handleTimeRangeChange} />
      </div>

      {/* Timeline content */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {loading && sessions.length === 0 ? (
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        ) : sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Inbox className="w-8 h-8 text-slate-300 dark:text-slate-600 mb-3" />
            <p className="text-sm text-slate-400 dark:text-slate-500">
              No activity in this time range
            </p>
            <p className="text-[10px] text-slate-400 dark:text-slate-600 mt-1">
              Try a wider range or wait for the next heartbeat
            </p>
          </div>
        ) : (
          <div className="space-y-1.5">
            {groupedSessions.map((group) => (
              <div key={group.date}>
                <DateDivider date={group.date} />
                <div className="space-y-1.5">
                  {group.items.map((session) =>
                    isHeartbeatSession(session) ? (
                      <HeartbeatSessionCard
                        key={session.id}
                        id={session.id}
                        summary={session.summary_oneliner}
                        status={session.status}
                        messageCount={session.message_count}
                        createdAt={session.created_at}
                        eventsPreview={session.events_preview}
                      />
                    ) : (
                      <ChatSessionCard
                        key={session.id}
                        session={session}
                        onSelect={onSelectChatSession}
                      />
                    ),
                  )}
                </div>
              </div>
            ))}

            {/* Load more */}
            {sessions.length < total && (
              <div className="flex justify-center pt-4 pb-2">
                <button
                  onClick={handleLoadMore}
                  disabled={loading}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-medium text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 bg-slate-100/50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                >
                  {loading ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    `Load more (${total - sessions.length} remaining)`
                  )}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
