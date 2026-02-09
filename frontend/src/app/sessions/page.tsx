"use client";

import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { useQueryClient, useInfiniteQuery } from "@tanstack/react-query";
import { AlertCircle, RefreshCw, X } from "lucide-react";
import {
  fetchSessions,
  fetchSession,
  fetchSessionEvents,
  type Session,
  type SessionEventsResponse,
} from "@/lib/api";
import { useSessionEvents } from "@/hooks/use-session-events";
import { LiveBadge, EventStream } from "@/components/monitoring";
import { estimateCost } from "./utils";
import { REFRESH_OPTIONS, REFRESH_STORAGE_KEY, SORT_STORAGE_KEY, type RefreshInterval, type SortField, type SortDirection } from "./types";
import { SessionTable } from "./components/SessionTable";
import { SessionsHeader } from "./components/SessionsHeader";

export default function SessionsPage() {
  const queryClient = useQueryClient();
  const tableRef = useRef<HTMLDivElement>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [projectFilter, setProjectFilter] = useState<string>("");
  const [modelFilter, setModelFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState("");
  const [showLiveView, setShowLiveView] = useState(false);
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);
  const [expandedSessionData, setExpandedSessionData] = useState<Session | null>(null);
  const [expandedEventsData, setExpandedEventsData] = useState<SessionEventsResponse | null>(null);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);
  const [refreshInterval, setRefreshInterval] = useState<RefreshInterval>(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [sortField, setSortField] = useState<SortField>("time");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [focusedRowIndex, setFocusedRowIndex] = useState<number>(-1);
  const [flashingSessionIds, setFlashingSessionIds] = useState<Set<string>>(new Set());
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

  // Fetch session details and events when expanded
  const handleToggleExpand = async (sessionId: string) => {
    if (expandedSessionId === sessionId) {
      setExpandedSessionId(null);
      setExpandedSessionData(null);
      setExpandedEventsData(null);
      return;
    }
    setExpandedSessionId(sessionId);
    setIsLoadingDetails(true);
    try {
      const [sessionData, eventsData] = await Promise.all([
        fetchSession(sessionId),
        fetchSessionEvents(sessionId, { page_size: 500 }),
      ]);
      setExpandedSessionData(sessionData);
      setExpandedEventsData(eventsData);
    } catch {
      setExpandedSessionData(null);
      setExpandedEventsData(null);
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

  const {
    data,
    isLoading,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["sessions", { status: statusFilter, project: projectFilter, pageSize }],
    queryFn: ({ pageParam = 1 }) =>
      fetchSessions({
        page: pageParam,
        page_size: pageSize,
        status: statusFilter || undefined,
        project_id: projectFilter || undefined,
      }),
    getNextPageParam: (lastPage) => {
      const totalPages = Math.ceil(lastPage.total / lastPage.page_size);
      return lastPage.page < totalPages ? lastPage.page + 1 : undefined;
    },
    initialPageParam: 1,
  });

  // Flatten all pages into single array
  const allSessions = useMemo(() =>
    data?.pages.flatMap((page) => page.sessions) ?? [],
    [data]
  );
  const total = data?.pages[0]?.total ?? 0;

  // Scroll handler for infinite loading
  const handleScroll = useCallback(() => {
    if (!tableRef.current || isFetchingNextPage || !hasNextPage) return;
    const { scrollTop, scrollHeight, clientHeight } = tableRef.current;
    if (scrollHeight - scrollTop - clientHeight < 500) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Filter and sort sessions
  const sortedSessions = useMemo(() => {
    let sessions = allSessions;

    // Filter by model (click-to-filter)
    if (modelFilter) {
      sessions = sessions.filter((s) => s.model === modelFilter);
    }

    // Filter by search
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      sessions = sessions.filter(
        (s) =>
          s.id.toLowerCase().includes(query) ||
          s.project_id.toLowerCase().includes(query) ||
          s.model.toLowerCase().includes(query) ||
          s.agent_slug?.toLowerCase().includes(query)
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
        case "tokens":
          cmp = (a.total_input_tokens + a.total_output_tokens) - (b.total_input_tokens + b.total_output_tokens);
          break;
        case "cost": {
          const costA = estimateCost(a.model, a.total_input_tokens, a.total_output_tokens);
          const costB = estimateCost(b.model, b.total_input_tokens, b.total_output_tokens);
          cmp = costA - costB;
          break;
        }
        case "time":
          cmp = new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime();
          break;
      }
      return sortDirection === "asc" ? cmp : -cmp;
    });

    return sorted;
  }, [allSessions, modelFilter, searchQuery, sortField, sortDirection]);

  // Keyboard navigation handler
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!sortedSessions.length) return;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setFocusedRowIndex((prev) => Math.min(prev + 1, sortedSessions.length - 1));
          break;
        case "ArrowUp":
          e.preventDefault();
          setFocusedRowIndex((prev) => Math.max(prev - 1, 0));
          break;
        case "Enter":
        case " ":
          e.preventDefault();
          if (focusedRowIndex >= 0 && focusedRowIndex < sortedSessions.length) {
            handleToggleExpand(sortedSessions[focusedRowIndex].id);
          }
          break;
        case "Escape":
          e.preventDefault();
          setExpandedSessionId(null);
          setExpandedSessionData(null);
          break;
      }
    },
    [sortedSessions, focusedRowIndex]
  );

  // Calculate page stats
  const pageStats = useMemo(() => {
    if (!sortedSessions.length) return null;
    const totalTokens = sortedSessions.reduce(
      (sum, s) => sum + s.total_input_tokens + s.total_output_tokens,
      0
    );
    const totalCost = sortedSessions.reduce(
      (sum, s) => sum + estimateCost(s.model, s.total_input_tokens, s.total_output_tokens),
      0
    );
    return { totalTokens, totalCost };
  }, [sortedSessions]);

  const handleModelFilterClick = (model: string) => {
    setModelFilter(modelFilter === model ? "" : model);
  };

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      <SessionsHeader
        total={total}
        pageStats={pageStats}
        searchQuery={searchQuery}
        statusFilter={statusFilter}
        projectFilter={projectFilter}
        refreshInterval={refreshInterval}
        isRefreshing={isRefreshing}
        showLiveView={showLiveView}
        wsStatus={wsStatus}
        onSearchChange={setSearchQuery}
        onStatusFilterChange={setStatusFilter}
        onProjectFilterChange={setProjectFilter}
        onRefreshChange={handleRefreshChange}
        onToggleLiveView={() => setShowLiveView(!showLiveView)}
      />

      <main className="px-6 lg:px-8 py-5">
        {/* Live Events Panel */}
        {showLiveView && (
          <div className="mb-5 rounded-lg border border-green-200 dark:border-green-800 bg-white dark:bg-slate-900 overflow-hidden">
            <div className="px-4 py-2 bg-green-50 dark:bg-green-950/30 border-b border-green-200 dark:border-green-800 flex items-center gap-2">
              <LiveBadge size="sm" />
              <span className="text-xs font-semibold text-green-700 dark:text-green-300">
                Real-time Events
              </span>
              <span className="text-[10px] text-green-600 dark:text-green-400 ml-auto font-mono tabular-nums">
                {events.length}
              </span>
            </div>
            <EventStream events={events} maxHeight="200px" />
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="flex items-center gap-2 p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 mb-5">
            <AlertCircle className="h-4 w-4" />
            <p className="text-xs font-medium">Failed to load sessions</p>
          </div>
        )}

        {/* Active model filter indicator */}
        {modelFilter && (
          <div className="mb-4 flex items-center gap-2">
            <span className="text-xs text-slate-500 dark:text-slate-400">Filtered by model:</span>
            <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
              {modelFilter}
              <button
                onClick={() => setModelFilter("")}
                className="ml-1 p-0.5 rounded-full hover:bg-purple-200 dark:hover:bg-purple-800 transition-colors"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          </div>
        )}

        {/* Loading - Skeleton rows */}
        {isLoading && (
          <div className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
            {/* Skeleton header */}
            <div className="h-10 bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-700" />
            {/* Skeleton rows */}
            {Array.from({ length: 10 }).map((_, i) => (
              <div
                key={i}
                className="grid grid-cols-[80px_minmax(120px,1fr)_minmax(140px,1.5fr)_130px_100px_80px_70px_36px] gap-3 px-4 py-3 border-b border-slate-100 dark:border-slate-800/50"
              >
                <div className="h-4 w-16 rounded animate-shimmer" />
                <div className="h-4 w-24 rounded animate-shimmer" />
                <div className="h-4 w-32 rounded animate-shimmer" />
                <div className="h-5 w-20 rounded-full animate-shimmer" />
                <div className="h-4 w-16 rounded animate-shimmer ml-auto" />
                <div className="h-4 w-14 rounded animate-shimmer ml-auto" />
                <div className="h-4 w-12 rounded animate-shimmer ml-auto" />
                <div className="h-4 w-4 rounded animate-shimmer ml-auto" />
              </div>
            ))}
          </div>
        )}

        {/* SESSIONS TABLE */}
        {data && (
          <>
            <SessionTable
              sessions={sortedSessions}
              sortField={sortField}
              sortDirection={sortDirection}
              modelFilter={modelFilter}
              expandedSessionId={expandedSessionId}
              expandedSessionData={expandedSessionData}
              expandedEventsData={expandedEventsData}
              isLoadingDetails={isLoadingDetails}
              liveSessionIds={liveSessionIds}
              focusedRowIndex={focusedRowIndex}
              flashingSessionIds={flashingSessionIds}
              tableRef={tableRef}
              onSort={handleSort}
              onKeyDown={handleKeyDown}
              onScroll={handleScroll}
              onToggleExpand={handleToggleExpand}
              onModelFilterClick={handleModelFilterClick}
            />

            {/* Infinite scroll loading indicator */}
            {isFetchingNextPage && (
              <div className="flex items-center justify-center py-4 mt-3">
                <div className="flex items-center gap-2 text-slate-400 text-sm">
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Loading more sessions...
                </div>
              </div>
            )}

            {/* End of list indicator */}
            {!hasNextPage && allSessions.length > 0 && !isFetchingNextPage && (
              <div className="flex items-center justify-center py-3 mt-3 text-xs text-slate-500 bg-slate-50 dark:bg-slate-900/50 rounded-lg">
                Showing all {allSessions.length} of {total} sessions
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
