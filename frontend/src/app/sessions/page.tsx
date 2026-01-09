"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  MessageSquare,
  Clock,
  Filter,
  ChevronLeft,
  ChevronRight,
  Cpu,
  Server,
  Search,
  AlertCircle,
  Radio,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchSessions, type SessionListItem } from "@/lib/api";
import { useSessionEvents } from "@/hooks/use-session-events";
import { LiveBadge, EventStream } from "@/components/monitoring";

const STATUS_COLORS: Record<
  string,
  { bg: string; text: string; label: string }
> = {
  active: {
    bg: "bg-emerald-100 dark:bg-emerald-900/30",
    text: "text-emerald-700 dark:text-emerald-400",
    label: "Active",
  },
  completed: {
    bg: "bg-slate-100 dark:bg-slate-800",
    text: "text-slate-600 dark:text-slate-400",
    label: "Completed",
  },
  error: {
    bg: "bg-red-100 dark:bg-red-900/30",
    text: "text-red-700 dark:text-red-400",
    label: "Error",
  },
};

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));

  if (days === 0) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } else if (days === 1) {
    return "Yesterday";
  } else if (days < 7) {
    return `${days} days ago`;
  }
  return date.toLocaleDateString();
}

function getProviderIcon(provider: string) {
  if (provider === "claude") {
    return <Cpu className="h-4 w-4 text-orange-600 dark:text-orange-400" />;
  }
  return <Server className="h-4 w-4 text-blue-600 dark:text-blue-400" />;
}

export default function SessionsPage() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState("");
  const [showLiveView, setShowLiveView] = useState(false);
  const pageSize = 20;

  // Real-time events subscription
  const { events, status: wsStatus } = useSessionEvents({
    autoConnect: showLiveView,
    autoReconnect: showLiveView,
  });

  // Track live session IDs from recent events
  const liveSessionIds = useMemo(() => {
    const recentEvents = events.filter(
      (e) => new Date().getTime() - new Date(e.timestamp).getTime() < 60000,
    );
    return new Set(recentEvents.map((e) => e.session_id));
  }, [events]);

  const { data, isLoading, error } = useQuery({
    queryKey: ["sessions", { page, status: statusFilter, pageSize }],
    queryFn: () =>
      fetchSessions({
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
      }),
  });

  const filteredSessions = data?.sessions.filter((session) => {
    if (!searchQuery) return true;
    const query = searchQuery.toLowerCase();
    return (
      session.id.toLowerCase().includes(query) ||
      session.project_id.toLowerCase().includes(query) ||
      session.model.toLowerCase().includes(query)
    );
  });

  const totalPages = data ? Math.ceil(data.total / pageSize) : 0;

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Page Header */}
      <header className="sticky top-0 z-10 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-3">
              <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                Sessions
              </h1>
              <span className="text-sm text-slate-500 dark:text-slate-400">
                {data?.total ?? 0} total
              </span>
            </div>

            {/* Filters */}
            <div className="flex items-center gap-3">
              {/* Search */}
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search sessions..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9 pr-4 py-1.5 w-48 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {/* Status Filter */}
              <div className="flex items-center gap-1.5">
                <Filter className="h-4 w-4 text-slate-400" />
                <select
                  value={statusFilter}
                  onChange={(e) => {
                    setStatusFilter(e.target.value);
                    setPage(1);
                  }}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">All status</option>
                  <option value="active">Active</option>
                  <option value="completed">Completed</option>
                </select>
              </div>

              {/* Live View Toggle */}
              <button
                onClick={() => setShowLiveView(!showLiveView)}
                className={cn(
                  "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                  showLiveView
                    ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 border border-green-200 dark:border-green-800"
                    : "bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700",
                )}
              >
                <Radio className="h-4 w-4" />
                {showLiveView ? (
                  <span className="flex items-center gap-1.5">
                    Live
                    {wsStatus === "connected" && (
                      <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                    )}
                  </span>
                ) : (
                  "Live View"
                )}
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-8">
        {/* Live Events Panel */}
        {showLiveView && (
          <div className="mb-6 rounded-lg border border-green-200 dark:border-green-800 bg-white dark:bg-slate-900 overflow-hidden">
            <div className="px-4 py-2 bg-green-50 dark:bg-green-950/30 border-b border-green-200 dark:border-green-800 flex items-center gap-2">
              <LiveBadge size="sm" />
              <span className="text-sm font-medium text-green-700 dark:text-green-300">
                Real-time Events
              </span>
              <span className="text-xs text-green-600 dark:text-green-400 ml-auto">
                {events.length} events
              </span>
            </div>
            <EventStream events={events} maxHeight="300px" />
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="flex items-center gap-2 p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 mb-6">
            <AlertCircle className="h-5 w-5" />
            <p className="text-sm">Failed to load sessions</p>
          </div>
        )}

        {/* Loading State */}
        {isLoading && (
          <div className="flex items-center justify-center py-12 text-slate-500">
            Loading sessions...
          </div>
        )}

        {/* Sessions List */}
        {data && (
          <>
            {filteredSessions?.length === 0 ? (
              <div className="text-center py-12 text-slate-500 dark:text-slate-400">
                <MessageSquare className="h-12 w-12 mx-auto mb-3 opacity-30" />
                <p>No sessions found</p>
              </div>
            ) : (
              <div className="space-y-2">
                {filteredSessions?.map((session) => (
                  <SessionCard
                    key={session.id}
                    session={session}
                    isLive={liveSessionIds.has(session.id)}
                  />
                ))}
              </div>
            )}

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-4 mt-8">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-medium bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-50 dark:hover:bg-slate-700"
                >
                  <ChevronLeft className="h-4 w-4" />
                  Previous
                </button>
                <span className="text-sm text-slate-500">
                  Page {page} of {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-medium bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-50 dark:hover:bg-slate-700"
                >
                  Next
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}

interface SessionCardProps {
  session: SessionListItem;
  isLive?: boolean;
}

function SessionCard({ session, isLive = false }: SessionCardProps) {
  const status = STATUS_COLORS[session.status] || STATUS_COLORS.completed;

  return (
    <Link
      href={`/sessions/${session.id}`}
      className={cn(
        "block p-4 rounded-lg border transition-all",
        "hover:shadow-md",
        isLive
          ? "border-green-200 dark:border-green-800 bg-green-50/50 dark:bg-green-950/20"
          : "border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-700",
      )}
    >
      <div className="flex items-center gap-4">
        {/* Provider icon */}
        <div className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800">
          {getProviderIcon(session.provider)}
        </div>

        {/* Session info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <code className="text-sm font-mono text-slate-700 dark:text-slate-300 truncate">
              {session.id.slice(0, 8)}...
            </code>
            <span
              className={cn(
                "px-2 py-0.5 rounded text-xs font-medium",
                status.bg,
                status.text,
              )}
            >
              {status.label}
            </span>
            {isLive && <LiveBadge size="sm" />}
          </div>
          <div className="mt-1 flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
            <span>{session.model}</span>
            <span className="text-slate-300 dark:text-slate-600">|</span>
            <span>{session.project_id}</span>
          </div>
        </div>

        {/* Message count */}
        <div className="text-right">
          <div className="flex items-center gap-1.5 text-slate-600 dark:text-slate-400">
            <MessageSquare className="h-4 w-4" />
            <span className="text-sm font-medium">{session.message_count}</span>
          </div>
          <div className="flex items-center gap-1 text-xs text-slate-400 mt-1">
            <Clock className="h-3 w-3" />
            <span>{formatDate(session.updated_at)}</span>
          </div>
        </div>
      </div>
    </Link>
  );
}
