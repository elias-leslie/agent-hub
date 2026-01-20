"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Search,
  AlertCircle,
  RefreshCw,
  Gauge,
  Copy,
  Check,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  MessageSquare,
  Maximize2,
  Minimize2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchSessions,
  fetchSession,
  type SessionListItem,
  type Session,
} from "@/lib/api";
import { useSessionEvents } from "@/hooks/use-session-events";
import { LiveBadge, EventStream } from "@/components/monitoring";

// ─────────────────────────────────────────────────────────────────────────────
// CONSTANTS & TYPES
// ─────────────────────────────────────────────────────────────────────────────

const REFRESH_OPTIONS = [
  { value: 0, label: "Manual" },
  { value: 5000, label: "5s" },
  { value: 15000, label: "15s" },
  { value: 30000, label: "30s" },
  { value: 60000, label: "60s" },
] as const;

type RefreshInterval = (typeof REFRESH_OPTIONS)[number]["value"];
type SortField = "project" | "model" | "status" | "messages" | "time";
type SortDirection = "asc" | "desc";

const REFRESH_STORAGE_KEY = "sessions-auto-refresh";
const SORT_STORAGE_KEY = "sessions-sort";

// ─────────────────────────────────────────────────────────────────────────────
// FORMATTERS
// ─────────────────────────────────────────────────────────────────────────────

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffSecs < 10) return "just now";
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatTokens(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
  return tokens.toString();
}

function formatCost(cost: number): string {
  if (cost === 0) return "$0";
  if (cost < 0.0001) return `$${cost.toFixed(6)}`;
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(2)}`;
}

function formatDuration(startDate: string, endDate: string): string {
  const start = new Date(startDate).getTime();
  const end = new Date(endDate).getTime();
  const diffMs = end - start;
  if (diffMs < 1000) return `${diffMs}ms`;
  if (diffMs < 60000) return `${(diffMs / 1000).toFixed(1)}s`;
  return `${Math.floor(diffMs / 60000)}m ${Math.floor((diffMs % 60000) / 1000)}s`;
}

// ─────────────────────────────────────────────────────────────────────────────
// MODEL BADGE
// ─────────────────────────────────────────────────────────────────────────────

function ModelBadge({ model, provider }: { model: string; provider: string }) {
  const isClaude = provider === "claude";
  const shortName = model
    .replace("claude-", "")
    .replace("gemini-", "")
    .replace("-preview", "")
    .slice(0, 14);

  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium border tabular-nums",
        isClaude
          ? "border-orange-300 dark:border-orange-700 text-orange-700 dark:text-orange-300 bg-orange-50 dark:bg-orange-950/30"
          : "border-blue-300 dark:border-blue-700 text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950/30"
      )}
    >
      {shortName}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// STATUS INDICATOR
// ─────────────────────────────────────────────────────────────────────────────

function StatusIndicator({ status, isLive }: { status: string; isLive?: boolean }) {
  const config = {
    active: {
      dot: "bg-blue-500",
      pulse: true,
      bg: "",
    },
    completed: {
      dot: "bg-slate-400 dark:bg-slate-500",
      pulse: false,
      bg: "",
    },
    error: {
      dot: "bg-red-500",
      pulse: false,
      bg: "bg-red-50 dark:bg-red-950/20",
    },
  }[status] || { dot: "bg-slate-400", pulse: false, bg: "" };

  return (
    <div className={cn("flex items-center justify-center w-8 h-8 rounded-lg", config.bg)}>
      <span
        className={cn(
          "w-2.5 h-2.5 rounded-full",
          config.dot,
          (config.pulse || isLive) && "animate-pulse"
        )}
      />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SORTABLE HEADER
// ─────────────────────────────────────────────────────────────────────────────

function SortableHeader({
  label,
  field,
  currentField,
  direction,
  onSort,
  className,
}: {
  label: string;
  field: SortField;
  currentField: SortField;
  direction: SortDirection;
  onSort: (field: SortField) => void;
  className?: string;
}) {
  const isActive = currentField === field;

  return (
    <button
      onClick={() => onSort(field)}
      className={cn(
        "flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors",
        isActive && "text-slate-700 dark:text-slate-200",
        className
      )}
    >
      {label}
      {isActive ? (
        direction === "asc" ? (
          <ArrowUp className="h-3 w-3" />
        ) : (
          <ArrowDown className="h-3 w-3" />
        )
      ) : (
        <ArrowUpDown className="h-3 w-3 opacity-40" />
      )}
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// COPY ID BUTTON
// ─────────────────────────────────────────────────────────────────────────────

function CopyIdButton({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await navigator.clipboard.writeText(id);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
      title="Copy session ID"
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-emerald-500" />
      ) : (
        <Copy className="h-3.5 w-3.5 text-slate-400" />
      )}
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// EXPANDED ROW - THREE PANE LAYOUT (Viewport-Constrained with Sticky Sidebars)
// ─────────────────────────────────────────────────────────────────────────────

function ExpandedRowContent({
  session,
  expandedData,
  isLoading,
}: {
  session: SessionListItem;
  expandedData: Session | null;
  isLoading: boolean;
}) {
  const [isWidthExpanded, setIsWidthExpanded] = useState(false);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-slate-500">
        <RefreshCw className="h-4 w-4 animate-spin mr-2" />
        Loading session details...
      </div>
    );
  }

  if (!expandedData) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-slate-500">
        Failed to load session details
      </div>
    );
  }

  const messageCount = expandedData.messages?.length || 0;

  return (
    <div
      className={cn(
        "relative overflow-y-auto transition-all duration-300",
        "min-h-[300px] max-h-[65vh]"
      )}
    >
      <div
        className={cn(
          "grid gap-4 p-4 transition-all duration-300",
          isWidthExpanded
            ? "grid-cols-1"
            : "grid-cols-[20%_1fr_25%]"
        )}
      >
        {/* METRICS PANE (20%) - Sticky */}
        {!isWidthExpanded && (
          <div className="sticky top-0 self-start space-y-4">
            <h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Metrics
            </h4>

            {/* Context Usage Meter */}
            {expandedData.context_usage && (
              <div>
                <div className="flex items-center justify-between text-[11px] text-slate-500 mb-1.5">
                  <span className="flex items-center gap-1">
                    <Gauge className="h-3 w-3" /> Context
                  </span>
                  <span className="font-mono tabular-nums">
                    {expandedData.context_usage.percent_used.toFixed(0)}%
                  </span>
                </div>
                <div className="h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      expandedData.context_usage.percent_used > 90
                        ? "bg-red-500"
                        : expandedData.context_usage.percent_used > 70
                          ? "bg-amber-500"
                          : "bg-emerald-500"
                    )}
                    style={{
                      width: `${Math.min(100, expandedData.context_usage.percent_used)}%`,
                    }}
                  />
                </div>
                <div className="flex justify-between text-[10px] text-slate-400 mt-1 font-mono tabular-nums">
                  <span>{formatTokens(expandedData.context_usage.used_tokens)}</span>
                  <span>{formatTokens(expandedData.context_usage.limit_tokens)}</span>
                </div>
              </div>
            )}

            {/* Token Summary */}
            <div className="grid grid-cols-2 gap-2">
              <div className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800/50">
                <p className="text-[10px] text-slate-400 uppercase tracking-wide">Input</p>
                <p className="text-sm font-semibold font-mono tabular-nums text-emerald-600 dark:text-emerald-400">
                  {formatTokens(expandedData.total_input_tokens || 0)}
                </p>
              </div>
              <div className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800/50">
                <p className="text-[10px] text-slate-400 uppercase tracking-wide">Output</p>
                <p className="text-sm font-semibold font-mono tabular-nums text-blue-600 dark:text-blue-400">
                  {formatTokens(expandedData.total_output_tokens || 0)}
                </p>
              </div>
            </div>

            {/* Duration */}
            <div className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800/50">
              <p className="text-[10px] text-slate-400 uppercase tracking-wide">Duration</p>
              <p className="text-sm font-semibold font-mono tabular-nums text-slate-700 dark:text-slate-200">
                {formatDuration(expandedData.created_at, expandedData.updated_at)}
              </p>
            </div>
          </div>
        )}

        {/* TRANSCRIPT PANE (55% or 100% when expanded) */}
        <div className={cn(
          "flex flex-col",
          !isWidthExpanded && "border-x border-slate-200 dark:border-slate-700 px-4"
        )}>
          {/* Sticky header for transcript */}
          <div className="sticky top-0 z-10 flex items-center justify-between pb-3 bg-slate-50/95 dark:bg-slate-800/95 backdrop-blur-sm -mx-4 px-4 pt-1">
            <div className="flex items-center gap-3">
              <h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                Messages
              </h4>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300 tabular-nums">
                {messageCount}
              </span>
            </div>
            <button
              onClick={() => setIsWidthExpanded(!isWidthExpanded)}
              className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-medium text-slate-500 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
              title={isWidthExpanded ? "Show sidebars" : "Expand transcript"}
            >
              {isWidthExpanded ? (
                <>
                  <Minimize2 className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Collapse</span>
                </>
              ) : (
                <>
                  <Maximize2 className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Expand</span>
                </>
              )}
            </button>
          </div>

          {/* Messages - ALL messages, scrollable */}
          <div className="space-y-2 pr-2">
            {expandedData.messages && expandedData.messages.length > 0 ? (
              expandedData.messages.map((msg) => (
                <div
                  key={msg.id}
                  className={cn(
                    "p-3 rounded-lg text-xs",
                    msg.role === "user"
                      ? "bg-blue-50 dark:bg-blue-950/30 border-l-2 border-blue-400"
                      : msg.role === "assistant"
                        ? "bg-slate-100 dark:bg-slate-800/70 border-l-2 border-slate-400"
                        : "bg-amber-50 dark:bg-amber-950/30 border-l-2 border-amber-400"
                  )}
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="font-semibold capitalize text-slate-700 dark:text-slate-200">
                      {msg.role}
                    </span>
                    {msg.agent_name && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-200 dark:bg-slate-700 text-slate-500 dark:text-slate-400">
                        {msg.agent_name}
                      </span>
                    )}
                    {msg.tokens && (
                      <span className="text-[10px] text-slate-400 font-mono tabular-nums ml-auto">
                        {formatTokens(msg.tokens)} tok
                      </span>
                    )}
                  </div>
                  <p className="text-slate-600 dark:text-slate-300 whitespace-pre-wrap break-words leading-relaxed">
                    {msg.content}
                  </p>
                </div>
              ))
            ) : (
              <p className="text-sm text-slate-400 text-center py-8">No messages</p>
            )}
          </div>
        </div>

        {/* META PANE (25%) - Sticky */}
        {!isWidthExpanded && (
          <div className="sticky top-0 self-start space-y-4">
            <h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Session Info
            </h4>

            {/* ID with copy */}
            <div>
              <p className="text-[10px] text-slate-400 uppercase tracking-wide mb-1">Session ID</p>
              <div className="flex items-center gap-2">
                <code className="text-[11px] font-mono text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 px-2 py-1 rounded truncate flex-1">
                  {session.id}
                </code>
                <CopyIdButton id={session.id} />
              </div>
            </div>

            {/* Purpose */}
            {expandedData.purpose && (
              <div>
                <p className="text-[10px] text-slate-400 uppercase tracking-wide mb-1">Purpose</p>
                <p className="text-xs text-slate-700 dark:text-slate-200">{expandedData.purpose}</p>
              </div>
            )}

            {/* Agent breakdown */}
            {expandedData.agent_token_breakdown && expandedData.agent_token_breakdown.length > 0 && (
              <div>
                <p className="text-[10px] text-slate-400 uppercase tracking-wide mb-2">Agents</p>
                <div className="space-y-1.5">
                  {expandedData.agent_token_breakdown.map((agent) => (
                    <div
                      key={agent.agent_id}
                      className="flex items-center justify-between text-[11px] p-1.5 rounded bg-slate-100 dark:bg-slate-800/50"
                    >
                      <span className="text-slate-600 dark:text-slate-300 truncate">
                        {agent.agent_name || agent.agent_id.slice(0, 8)}
                      </span>
                      <span className="font-mono tabular-nums text-slate-500">
                        {formatTokens(agent.total_tokens)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Timestamps */}
            <div className="text-[10px] text-slate-400 space-y-1">
              <div className="flex justify-between">
                <span>Created</span>
                <span className="font-mono tabular-nums">
                  {new Date(expandedData.created_at).toLocaleTimeString()}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Updated</span>
                <span className="font-mono tabular-nums">
                  {new Date(expandedData.updated_at).toLocaleTimeString()}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN SESSIONS PAGE
// ─────────────────────────────────────────────────────────────────────────────

export default function SessionsPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [projectFilter, setProjectFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState("");
  const [showLiveView, setShowLiveView] = useState(false);
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);
  const [expandedSessionData, setExpandedSessionData] = useState<Session | null>(null);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);
  const [refreshInterval, setRefreshInterval] = useState<RefreshInterval>(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [sortField, setSortField] = useState<SortField>("time");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const pageSize = 25;

  // Load preferences from localStorage
  useEffect(() => {
    const storedRefresh = localStorage.getItem(REFRESH_STORAGE_KEY);
    if (storedRefresh) {
      const parsed = parseInt(storedRefresh, 10);
      if (REFRESH_OPTIONS.some((opt) => opt.value === parsed)) {
        setRefreshInterval(parsed as RefreshInterval);
      }
    }

    const storedSort = localStorage.getItem(SORT_STORAGE_KEY);
    if (storedSort) {
      try {
        const { field, direction } = JSON.parse(storedSort);
        setSortField(field);
        setSortDirection(direction);
      } catch {
        // ignore
      }
    }
  }, []);

  const handleRefreshChange = useCallback((interval: RefreshInterval) => {
    setRefreshInterval(interval);
    localStorage.setItem(REFRESH_STORAGE_KEY, String(interval));
  }, []);

  const handleSort = useCallback(
    (field: SortField) => {
      const newDirection =
        sortField === field && sortDirection === "desc" ? "asc" : "desc";
      setSortField(field);
      setSortDirection(newDirection);
      localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify({ field, direction: newDirection }));
    },
    [sortField, sortDirection]
  );

  // Auto-refresh effect
  useEffect(() => {
    if (refreshInterval === 0) return;
    const intervalId = setInterval(() => {
      setIsRefreshing(true);
      queryClient.invalidateQueries({ queryKey: ["sessions"] }).finally(() => {
        setTimeout(() => setIsRefreshing(false), 500);
      });
    }, refreshInterval);
    return () => clearInterval(intervalId);
  }, [refreshInterval, queryClient]);

  // Fetch session details when expanded
  const handleToggleExpand = async (sessionId: string) => {
    if (expandedSessionId === sessionId) {
      setExpandedSessionId(null);
      setExpandedSessionData(null);
      return;
    }
    setExpandedSessionId(sessionId);
    setIsLoadingDetails(true);
    try {
      const data = await fetchSession(sessionId);
      setExpandedSessionData(data);
    } catch {
      setExpandedSessionData(null);
    } finally {
      setIsLoadingDetails(false);
    }
  };

  // Real-time events subscription
  const { events, status: wsStatus } = useSessionEvents({
    autoConnect: showLiveView,
    autoReconnect: showLiveView,
  });

  // Track live session IDs
  const liveSessionIds = useMemo(() => {
    const recentEvents = events.filter(
      (e) => new Date().getTime() - new Date(e.timestamp).getTime() < 60000
    );
    return new Set(recentEvents.map((e) => e.session_id));
  }, [events]);

  const { data, isLoading, error } = useQuery({
    queryKey: ["sessions", { page, status: statusFilter, project: projectFilter, pageSize }],
    queryFn: () =>
      fetchSessions({
        page,
        page_size: pageSize,
        status: statusFilter || undefined,
        project_id: projectFilter || undefined,
      }),
  });

  // Filter and sort sessions
  const sortedSessions = useMemo(() => {
    let sessions = data?.sessions || [];

    // Filter by search
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      sessions = sessions.filter(
        (s) =>
          s.id.toLowerCase().includes(query) ||
          s.project_id.toLowerCase().includes(query) ||
          s.model.toLowerCase().includes(query) ||
          s.purpose?.toLowerCase().includes(query)
      );
    }

    // Sort
    const sorted = [...sessions].sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "project":
          cmp = a.project_id.localeCompare(b.project_id);
          break;
        case "model":
          cmp = a.model.localeCompare(b.model);
          break;
        case "status":
          cmp = a.status.localeCompare(b.status);
          break;
        case "messages":
          cmp = a.message_count - b.message_count;
          break;
        case "time":
          cmp = new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime();
          break;
      }
      return sortDirection === "asc" ? cmp : -cmp;
    });

    return sorted;
  }, [data?.sessions, searchQuery, sortField, sortDirection]);

  const totalPages = data ? Math.ceil(data.total / pageSize) : 0;

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* HEADER */}
      <header className="sticky top-0 z-20 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-4">
              <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                Sessions
              </h1>
              <span className="text-sm font-mono tabular-nums text-slate-500 dark:text-slate-400">
                {data?.total ?? 0}
              </span>
            </div>

            {/* Controls */}
            <div className="flex items-center gap-3">
              {/* Search */}
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9 pr-4 py-1.5 w-40 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {/* Status Filter */}
              <select
                data-testid="filter-status"
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
                <option value="error">Error</option>
              </select>

              {/* Project Filter */}
              <input
                data-testid="filter-project"
                type="text"
                placeholder="Project..."
                value={projectFilter}
                onChange={(e) => {
                  setProjectFilter(e.target.value);
                  setPage(1);
                }}
                className="px-3 py-1.5 w-28 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />

              {/* Auto-refresh */}
              <div className="flex items-center gap-2">
                <RefreshCw
                  className={cn(
                    "h-4 w-4 text-slate-400",
                    isRefreshing && "animate-spin text-emerald-500"
                  )}
                />
                <select
                  data-testid="refresh-dropdown"
                  value={refreshInterval}
                  onChange={(e) => handleRefreshChange(parseInt(e.target.value, 10) as RefreshInterval)}
                  className={cn(
                    "px-3 py-1.5 rounded-lg border text-sm focus:outline-none focus:ring-2 focus:ring-blue-500",
                    refreshInterval > 0
                      ? "bg-emerald-50 dark:bg-emerald-900/30 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300"
                      : "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700"
                  )}
                >
                  {REFRESH_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                {refreshInterval > 0 && (
                  <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                )}
              </div>

              {/* Live View */}
              <button
                onClick={() => setShowLiveView(!showLiveView)}
                className={cn(
                  "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                  showLiveView
                    ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 border border-green-200 dark:border-green-800"
                    : "bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700"
                )}
              >
                {showLiveView ? (
                  <span className="flex items-center gap-1.5">
                    Live
                    {wsStatus === "connected" && (
                      <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                    )}
                  </span>
                ) : (
                  "Live"
                )}
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-6">
        {/* Live Events Panel */}
        {showLiveView && (
          <div className="mb-6 rounded-lg border border-green-200 dark:border-green-800 bg-white dark:bg-slate-900 overflow-hidden">
            <div className="px-4 py-2 bg-green-50 dark:bg-green-950/30 border-b border-green-200 dark:border-green-800 flex items-center gap-2">
              <LiveBadge size="sm" />
              <span className="text-sm font-medium text-green-700 dark:text-green-300">
                Real-time Events
              </span>
              <span className="text-xs text-green-600 dark:text-green-400 ml-auto font-mono tabular-nums">
                {events.length}
              </span>
            </div>
            <EventStream events={events} maxHeight="240px" />
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="flex items-center gap-2 p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 mb-6">
            <AlertCircle className="h-5 w-5" />
            <p className="text-sm">Failed to load sessions</p>
          </div>
        )}

        {/* Loading */}
        {isLoading && (
          <div className="flex items-center justify-center py-16 text-slate-500">
            <RefreshCw className="h-5 w-5 animate-spin mr-2" />
            Loading sessions...
          </div>
        )}

        {/* SESSIONS TABLE */}
        {data && (
          <>
            {sortedSessions.length === 0 ? (
              <div className="text-center py-16 text-slate-500 dark:text-slate-400">
                <MessageSquare className="h-12 w-12 mx-auto mb-3 opacity-30" />
                <p>No sessions found</p>
              </div>
            ) : (
              <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden">
                {/* TABLE HEADER */}
                <div className="sticky top-14 z-10 bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-700">
                  <div className="grid grid-cols-[40px_1fr_1fr_160px_100px_100px_40px] gap-4 px-4 py-3 items-center">
                    <div /> {/* Status column */}
                    <SortableHeader
                      label="Project"
                      field="project"
                      currentField={sortField}
                      direction={sortDirection}
                      onSort={handleSort}
                    />
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                      Purpose
                    </span>
                    <SortableHeader
                      label="Model"
                      field="model"
                      currentField={sortField}
                      direction={sortDirection}
                      onSort={handleSort}
                    />
                    <SortableHeader
                      label="Messages"
                      field="messages"
                      currentField={sortField}
                      direction={sortDirection}
                      onSort={handleSort}
                      className="justify-end"
                    />
                    <SortableHeader
                      label="Time"
                      field="time"
                      currentField={sortField}
                      direction={sortDirection}
                      onSort={handleSort}
                      className="justify-end"
                    />
                    <div /> {/* Expand column */}
                  </div>
                </div>

                {/* TABLE BODY */}
                <div className="divide-y divide-slate-100 dark:divide-slate-800">
                  {sortedSessions.map((session) => {
                    const isExpanded = expandedSessionId === session.id;
                    const isLive = liveSessionIds.has(session.id);

                    return (
                      <div
                        key={session.id}
                        data-testid="session-row"
                        className={cn(
                          "transition-colors",
                          isLive && "bg-blue-50/50 dark:bg-blue-950/10"
                        )}
                      >
                        {/* ROW */}
                        <button
                          onClick={() => handleToggleExpand(session.id)}
                          className="w-full grid grid-cols-[40px_1fr_1fr_160px_100px_100px_40px] gap-4 px-4 py-3 items-center text-left hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors group"
                        >
                          {/* Status */}
                          <StatusIndicator status={session.status} isLive={isLive} />

                          {/* Project */}
                          <div className="min-w-0">
                            <span className="text-sm font-medium text-slate-800 dark:text-slate-100 truncate block">
                              {session.project_id}
                            </span>
                          </div>

                          {/* Purpose */}
                          <div className="min-w-0">
                            <span className="text-sm text-slate-500 dark:text-slate-400 truncate block">
                              {session.purpose || "-"}
                            </span>
                          </div>

                          {/* Model */}
                          <ModelBadge model={session.model} provider={session.provider} />

                          {/* Messages */}
                          <div className="text-right">
                            <span className="text-sm font-mono tabular-nums text-slate-600 dark:text-slate-300">
                              {session.message_count}
                            </span>
                          </div>

                          {/* Time */}
                          <div className="text-right">
                            <span className="text-xs font-mono tabular-nums text-slate-500 dark:text-slate-400">
                              {formatRelativeTime(session.updated_at)}
                            </span>
                          </div>

                          {/* Expand / Actions */}
                          <div className="flex items-center justify-end gap-1">
                            <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                              <CopyIdButton id={session.id} />
                            </div>
                            <ChevronDown
                              className={cn(
                                "h-4 w-4 text-slate-400 transition-transform",
                                isExpanded && "rotate-180"
                              )}
                            />
                          </div>
                        </button>

                        {/* EXPANDED CONTENT */}
                        <div
                          className={cn(
                            "overflow-hidden transition-all duration-300 ease-out",
                            isExpanded ? "max-h-[70vh] opacity-100" : "max-h-0 opacity-0"
                          )}
                        >
                          <div className="border-t border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/20">
                            <ExpandedRowContent
                              session={session}
                              expandedData={isExpanded ? expandedSessionData : null}
                              isLoading={isExpanded && isLoadingDetails}
                            />
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* PAGINATION */}
            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-4 mt-6">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-medium bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-slate-50 dark:hover:bg-slate-700"
                >
                  <ChevronLeft className="h-4 w-4" />
                  Previous
                </button>
                <span className="text-sm font-mono tabular-nums text-slate-500">
                  {page} / {totalPages}
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
