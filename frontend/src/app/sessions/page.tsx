"use client";

import { useState, useMemo, useCallback, useRef } from "react";
import { useSessionEvents } from "@/hooks/use-session-events";
import { SessionTable } from "./components/SessionTable";
import { SessionsHeader } from "./components/SessionsHeader";
import { LiveEventsPanel } from "./components/LiveEventsPanel";
import { ModelFilterBadge } from "./components/ModelFilterBadge";
import { LoadingState } from "./components/LoadingState";
import { InfiniteScrollFooter } from "./components/InfiniteScrollFooter";
import { ErrorAlert } from "./components/ErrorAlert";
import { useSessionsData } from "./hooks/useSessionsData";
import { useSessionFilters } from "./hooks/useSessionFilters";
import { useSessionExpansion } from "./hooks/useSessionExpansion";
import { useSessionPreferences } from "./hooks/useSessionPreferences";
import { useSessionKeyboard } from "./hooks/useSessionKeyboard";

export default function SessionsPage() {
  const tableRef = useRef<HTMLDivElement>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [projectFilter, setProjectFilter] = useState<string>("");
  const [showLiveView, setShowLiveView] = useState(false);
  const [flashingSessionIds, setFlashingSessionIds] = useState<Set<string>>(new Set());
  const pageSize = 25;

  // Custom hooks for state management
  const { refreshInterval, isRefreshing, sortField, sortDirection, handleRefreshChange, handleSort } = 
    useSessionPreferences();

  const { data, allSessions, total, isLoading, error, fetchNextPage, hasNextPage, isFetchingNextPage } = 
    useSessionsData({ statusFilter, projectFilter, pageSize });

  const { modelFilter, setModelFilter, searchQuery, setSearchQuery, filteredAndSorted, pageStats } = 
    useSessionFilters({ sessions: allSessions, sortField, sortDirection });

  const { expandedSessionId, expandedSessionData, expandedEventsData, isLoadingDetails, handleToggleExpand, clearExpansion } = 
    useSessionExpansion();

  const { focusedRowIndex, handleKeyDown } = 
    useSessionKeyboard({ sessions: filteredAndSorted, onToggleExpand: handleToggleExpand, onClearExpansion: clearExpansion });

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

  // Scroll handler for infinite loading
  const handleScroll = useCallback(() => {
    if (!tableRef.current || isFetchingNextPage || !hasNextPage) return;
    const { scrollTop, scrollHeight, clientHeight } = tableRef.current;
    if (scrollHeight - scrollTop - clientHeight < 500) {
      fetchNextPage();
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

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
        {showLiveView && <LiveEventsPanel events={events} />}
        {error && <ErrorAlert />}
        <ModelFilterBadge modelFilter={modelFilter} onClear={() => setModelFilter("")} />
        {isLoading && <LoadingState />}
        
        {data && (
          <>
            <SessionTable
              sessions={filteredAndSorted}
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
            <InfiniteScrollFooter
              isFetchingNextPage={isFetchingNextPage}
              hasNextPage={hasNextPage}
              allSessionsLength={allSessions.length}
              total={total}
            />
          </>
        )}
      </main>
    </div>
  );
}
