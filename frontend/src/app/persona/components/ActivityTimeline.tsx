"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  MessageSquare,
  Loader2,
  Wrench,
  Inbox,
  ChevronRight,
  CheckCircle2,
} from "lucide-react";
import { formatDistanceToNow, format, isToday, isYesterday } from "date-fns";
import { cn } from "@/lib/utils";
import { fetchApi } from "@/lib/api-config";

import { TimeRangeDropdown, type TimeRange } from "./TimeRangeDropdown";
import { HeartbeatSessionCard } from "./HeartbeatSessionCard";
import { fixSpacing } from "../utils/text";

/* ── Types ─────────────────────────────────────────── */

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
  heartbeatRunning?: boolean;
  heartbeatLastRun?: string | null;
}
/* ── Helpers ───────────────────────────────────────── */

const isHeartbeatSession = (s: ActivitySession) =>
  s.session_type === "heartbeat";

const isActionHeartbeat = (s: ActivitySession) =>
  s.summary_oneliner?.startsWith("HEARTBEAT_ACTION") ?? false;

const isHighlight = (s: ActivitySession) =>
  !isHeartbeatSession(s) || isActionHeartbeat(s) || s.status === "failed";

function formatDateLabel(dateStr: string): string {
  const date = new Date(dateStr);
  if (isToday(date)) return "Today";
  if (isYesterday(date)) return "Yesterday";
  return format(date, "EEE, MMM d");
}

/* ── Health Pulse ──────────────────────────────────── */

function HealthPulse({
  sessions,
  running,
  lastRun,
}: {
  sessions: ActivitySession[];
  running: boolean;
  lastRun: string | null;
}) {
  const heartbeats = useMemo(
    () => sessions.filter(isHeartbeatSession).slice(0, 30).reverse(),
    [sessions],
  );

  const actionCount = heartbeats.filter(isActionHeartbeat).length;
  const errorCount = heartbeats.filter((s) => s.status === "failed").length;
  const totalChecks = heartbeats.length;

  return (
    <div className="flex items-center gap-4 px-4 py-2.5 border-b border-slate-200/30 dark:border-slate-800/60 bg-slate-50/50 dark:bg-slate-900/40 flex-shrink-0">
      {/* Status beacon */}
      <div className="flex items-center gap-2 flex-shrink-0">
        <div className="relative">
          <div
            className={cn(
              "w-2 h-2 rounded-full",
              running
                ? "bg-emerald-400"
                : lastRun
                  ? "bg-slate-400 dark:bg-slate-500"
                  : "bg-slate-300 dark:bg-slate-700",
            )}
          />
          {running && (
            <div className="absolute inset-0 w-2 h-2 rounded-full bg-emerald-400 animate-ping opacity-30" />
          )}
        </div>
        <span
          className={cn(
            "text-[10px] font-semibold font-mono uppercase tracking-wider",
            running
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-slate-400 dark:text-slate-500",
          )}
        >
          {running ? "Live" : "Idle"}
        </span>
      </div>

      {/* Last run */}
      {lastRun && (
        <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500 flex-shrink-0">
          {formatDistanceToNow(new Date(lastRun), { addSuffix: true })}
        </span>
      )}

      {/* Pulse dots */}
      {heartbeats.length > 0 && (
        <div className="flex items-center gap-[3px] flex-1 min-w-0 overflow-hidden">
          {heartbeats.map((hb) => {
            const isAction = isActionHeartbeat(hb);
            const isError = hb.status === "failed";
            return (
              <div
                key={hb.id}
                className={cn(
                  "rounded-full flex-shrink-0 transition-all",
                  isError
                    ? "w-2 h-2 bg-red-400 dark:bg-red-400"
                    : isAction
                      ? "w-2 h-2 bg-amber-400 dark:bg-amber-400"
                      : "w-1.5 h-1.5 bg-emerald-300/50 dark:bg-emerald-400/30",
                )}
                title={`${format(new Date(hb.created_at), "h:mm a")} — ${
                  isError ? "Error" : isAction ? "Action" : "OK"
                }`}
              />
            );
          })}
        </div>
      )}

      {/* Counts */}
      <div className="flex items-center gap-3 flex-shrink-0">
        {actionCount > 0 && (
          <span className="text-[10px] font-mono text-amber-600 dark:text-amber-400">
            {actionCount} action{actionCount !== 1 ? "s" : ""}
          </span>
        )}
        {errorCount > 0 && (
          <span className="text-[10px] font-mono text-red-500 dark:text-red-400">
            {errorCount} error{errorCount !== 1 ? "s" : ""}
          </span>
        )}
        {totalChecks > 0 && (
          <span className="text-[10px] font-mono text-slate-400 dark:text-slate-600">
            {totalChecks} check{totalChecks !== 1 ? "s" : ""}
          </span>
        )}
      </div>
    </div>
  );
}

/* ── Collapsed OK Group ────────────────────────────── */

function CollapsedOKGroup({ sessions }: { sessions: ActivitySession[] }) {
  const [expanded, setExpanded] = useState(false);

  if (sessions.length === 0) return null;

  const first = sessions[0];
  const last = sessions[sessions.length - 1];
  const timeRange =
    sessions.length > 1
      ? `${format(new Date(last.created_at), "h:mma").toLowerCase()} – ${format(new Date(first.created_at), "h:mma").toLowerCase()}`
      : format(new Date(first.created_at), "h:mma").toLowerCase();

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className={cn(
          "w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-all",
          "text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-400",
          "hover:bg-slate-100/50 dark:hover:bg-slate-800/30",
        )}
      >
        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400/50 dark:text-emerald-500/40 flex-shrink-0" />
        <span className="text-[11px] font-medium">
          {sessions.length} routine check{sessions.length !== 1 ? "s" : ""} passed
        </span>
        <span className="text-[10px] font-mono text-slate-400 dark:text-slate-600">
          {timeRange}
        </span>
        <ChevronRight
          className={cn(
            "w-3 h-3 ml-auto text-slate-400 dark:text-slate-600 transition-transform duration-150",
            expanded && "rotate-90",
          )}
        />
      </button>

      {expanded && (
        <div className="ml-3 mt-1 space-y-1 border-l border-slate-200/40 dark:border-slate-800/40 pl-3">
          {sessions.map((s) => (
            <HeartbeatSessionCard
              key={s.id}
              id={s.id}
              summary={s.summary_oneliner}
              status={s.status}
              messageCount={s.message_count}
              createdAt={s.created_at}
              eventsPreview={s.events_preview}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Chat Session Card ─────────────────────────────── */

function ChatSessionCard({
  session,
  onSelect,
}: {
  session: ActivitySession;
  onSelect?: (id: string) => void;
}) {
  const timeAgo = formatDistanceToNow(new Date(session.created_at), {
    addSuffix: true,
  });

  const contentPreview = session.events_preview?.find(
    (e) => e.content_preview && e.event_type !== "thinking",
  )?.content_preview;

  const toolCount =
    session.events_preview?.filter((e) => e.event_type === "tool_use").length ||
    0;

  return (
    <button
      onClick={() => onSelect?.(session.id)}
      className={cn(
        "w-full rounded-lg border transition-all duration-150 text-left",
        "border-slate-200/50 dark:border-slate-700/50",
        "hover:border-sky-300/40 dark:hover:border-sky-700/40",
        "bg-white/50 dark:bg-slate-800/30",
        "hover:bg-gradient-to-r hover:from-sky-50/30 hover:via-transparent hover:to-transparent",
        "dark:hover:from-sky-950/15 dark:hover:via-transparent dark:hover:to-transparent",
        "px-3 py-2.5 group",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 mt-1">
          <MessageSquare className="w-3.5 h-3.5 text-sky-400" />
        </div>

        <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500 flex-shrink-0 w-20 tabular-nums mt-0.5">
          {timeAgo}
        </span>

        <span className="flex-1 text-xs text-slate-600 dark:text-slate-300 line-clamp-2">
          {session.summary_oneliner
            ? fixSpacing(session.summary_oneliner)
            : session.session_type === "completion"
              ? "Autonomous run"
              : "Chat session"}
        </span>

        <div className="flex items-center gap-2 flex-shrink-0 mt-0.5">
          {toolCount > 0 && (
            <span className="flex items-center gap-0.5 text-[9px] font-mono text-amber-600 dark:text-amber-400">
              <Wrench className="w-2.5 h-2.5" />
              {toolCount}
            </span>
          )}
          <span className="flex items-center gap-1 text-[9px] font-mono text-slate-400 dark:text-slate-500">
            <MessageSquare className="w-2.5 h-2.5" />
            {session.message_count}
          </span>
        </div>
      </div>
      {contentPreview && (
        <p className="text-[10px] text-slate-400 dark:text-slate-500 truncate mt-1.5 ml-[44px]">
          {contentPreview}
        </p>
      )}
    </button>
  );
}

/* ── Date Divider ──────────────────────────────────── */

function DateDivider({ date }: { date: string }) {
  return (
    <div className="flex items-center gap-3 py-3">
      <div className="flex-1 h-px bg-gradient-to-r from-transparent via-slate-300/40 dark:via-slate-700/40 to-transparent" />
      <span className="text-[10px] font-mono font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider px-1">
        {date}
      </span>
      <div className="flex-1 h-px bg-gradient-to-r from-transparent via-slate-300/40 dark:via-slate-700/40 to-transparent" />
    </div>
  );
}

/* ── Skeleton ──────────────────────────────────────── */

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

/* ══ Main Component ════════════════════════════════════ */

export function ActivityTimeline({
  onSelectChatSession,
  heartbeatRunning = false,
  heartbeatLastRun = null,
}: ActivityTimelineProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [sessions, setSessions] = useState<ActivitySession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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
        if (!res.ok) {
          throw new Error(`Failed to fetch activity: ${res.status}`);
        }
        const data = await res.json();
        const newSessions = data.sessions || [];
        setSessions((prev) =>
          pageNum > 1 ? [...prev, ...newSessions] : newSessions,
        );
        setTotal(data.total || 0);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load activity");
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

  /* Group sessions by date, separating significant activity from routine OK checks */
  const groupedView = useMemo(() => {
    const groups: {
      date: string;
      highlights: ActivitySession[];
      okHeartbeats: ActivitySession[];
    }[] = [];
    let currentDate = "";

    for (const session of sessions) {
      const date = formatDateLabel(session.created_at);
      if (date !== currentDate) {
        currentDate = date;
        groups.push({ date, highlights: [], okHeartbeats: [] });
      }
      const group = groups[groups.length - 1];

      if (isHighlight(session)) {
        group.highlights.push(session);
      } else if (isHeartbeatSession(session)) {
        group.okHeartbeats.push(session);
      }
    }

    return groups;
  }, [sessions]);

  /* Stats */
  const okCount = useMemo(
    () =>
      sessions.filter(
        (s) => isHeartbeatSession(s) && !isActionHeartbeat(s) && s.status !== "failed",
      ).length,
    [sessions],
  );

  /* Derive last heartbeat run from sessions if prop not provided */
  const effectiveLastRun = useMemo(() => {
    if (heartbeatLastRun) return heartbeatLastRun;
    const latest = sessions.find(isHeartbeatSession);
    return latest?.created_at ?? null;
  }, [heartbeatLastRun, sessions]);

  /* Check if any session is currently active (running) */
  const effectiveRunning =
    heartbeatRunning || sessions.some((s) => isHeartbeatSession(s) && s.status === "active");

  const hasAnyContent = sessions.length > 0;
  const hasHighlights = groupedView.some((g) => g.highlights.length > 0);

  return (
    <div className="flex flex-col h-full">
      {/* Health pulse strip */}
      {!loading && hasAnyContent && (
        <HealthPulse
          sessions={sessions}
          running={effectiveRunning}
          lastRun={effectiveLastRun}
        />
      )}

      {/* Filter bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-slate-200/50 dark:border-slate-800/50 flex-shrink-0">
        <div className="min-w-0">
          <p className="text-[11px] font-medium text-slate-600 dark:text-slate-300">
            Single activity feed
          </p>
          <p className="text-[10px] text-slate-400 dark:text-slate-500">
            Routine heartbeat checks stay collapsed unless they need attention.
          </p>
        </div>
        <TimeRangeDropdown value={timeRange} onChange={handleTimeRangeChange} />
      </div>

      {/* Timeline content */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {error && sessions.length > 0 && (
          <div className="mb-3 rounded-lg border border-rose-200/60 bg-rose-50/80 px-3 py-2 text-xs text-rose-700 dark:border-rose-500/20 dark:bg-rose-950/20 dark:text-rose-300">
            Failed to refresh activity. Showing the last loaded results.
          </div>
        )}
        {loading && sessions.length === 0 ? (
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        ) : error && sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-12 h-12 rounded-full bg-rose-50 dark:bg-rose-950/30 flex items-center justify-center mb-4">
              <Inbox className="w-6 h-6 text-rose-300 dark:text-rose-500" />
            </div>
            <p className="text-sm font-medium text-rose-500 dark:text-rose-400">
              Failed to load activity
            </p>
            <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-1 max-w-[240px]">
              {error}
            </p>
          </div>
        ) : !hasAnyContent ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-12 h-12 rounded-full bg-slate-100 dark:bg-slate-800/50 flex items-center justify-center mb-4">
              <Inbox className="w-6 h-6 text-slate-300 dark:text-slate-600" />
            </div>
            <p className="text-sm font-medium text-slate-400 dark:text-slate-500">
              No activity in this time range
            </p>
            <p className="text-[10px] text-slate-400 dark:text-slate-600 mt-1 max-w-[220px]">
              Try a wider range or wait for the next heartbeat cycle
            </p>
          </div>
        ) : !hasHighlights && okCount > 0 ? (
          <div className="space-y-1.5">
            {groupedView.map((group) => {
              if (group.okHeartbeats.length === 0) return null;

              return (
                <div key={group.date}>
                  <DateDivider date={group.date} />
                  <CollapsedOKGroup sessions={group.okHeartbeats} />
                </div>
              );
            })}
          </div>
        ) : (
          <div className="space-y-1.5">
            {groupedView.map((group) => {
              // Skip empty groups (no highlights AND no ok heartbeats)
              if (
                group.highlights.length === 0 &&
                group.okHeartbeats.length === 0
              )
                return null;

              return (
                <div key={group.date}>
                  <DateDivider date={group.date} />
                  <div className="space-y-1.5">
                    {group.highlights.map((session) =>
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
                    {group.okHeartbeats.length > 0 && (
                      <CollapsedOKGroup sessions={group.okHeartbeats} />
                    )}
                  </div>
                </div>
              );
            })}

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
