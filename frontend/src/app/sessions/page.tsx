"use client";

import { useState, useCallback, useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useModels } from "@/components/chat/use-models";
import { buildModelCostMap } from "@/lib/model-pricing";
import { SessionTable } from "./components/SessionTable";
import { SessionsHeader } from "./components/SessionsHeader";
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
  const queryClient = useQueryClient();
  const tableRef = useRef<HTMLDivElement>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [hideBenchmarkTraffic, setHideBenchmarkTraffic] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const pageSize = 25;
  const models = useModels();
  const modelCosts = useMemo(() => buildModelCostMap(models), [models]);

  // Custom hooks for state management
  const { sortField, sortDirection, handleSort } =
    useSessionPreferences();

  const { data, allSessions, total, isLoading, error, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useSessionsData({ statusFilter, projectFilter: "", pageSize });

  const {
    modelFilter,
    setModelFilter,
    searchQuery,
    setSearchQuery,
    hiddenBenchmarkCount,
    filteredAndSorted,
    pageStats,
  } = useSessionFilters({
    sessions: allSessions,
    modelCosts,
    sortField,
    sortDirection,
    hideBenchmarkTraffic,
  });

  const { expandedSessionId, expandedSessionData, expandedEventsData, isLoadingDetails, handleToggleExpand, clearExpansion } =
    useSessionExpansion();

  const { focusedRowIndex, handleKeyDown } =
    useSessionKeyboard({ sessions: filteredAndSorted, onToggleExpand: handleToggleExpand, onClearExpansion: clearExpansion });

  // Manual refresh
  const handleRefresh = useCallback(() => {
    setIsRefreshing(true);
    queryClient.invalidateQueries({ queryKey: ["sessions"] }).finally(() => {
      setTimeout(() => setIsRefreshing(false), 500);
    });
  }, [queryClient]);

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
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />
      <SessionsHeader
        total={total}
        pageStats={pageStats}
        searchQuery={searchQuery}
        statusFilter={statusFilter}
        hideBenchmarkTraffic={hideBenchmarkTraffic}
        hiddenBenchmarkCount={hiddenBenchmarkCount}
        isRefreshing={isRefreshing}
        onSearchChange={setSearchQuery}
        onStatusFilterChange={setStatusFilter}
        onHideBenchmarkTrafficChange={setHideBenchmarkTraffic}
        onRefresh={handleRefresh}
      />

      <main className="page-frame">
        <div className="page-container">
        {error && <ErrorAlert />}
        <ModelFilterBadge modelFilter={modelFilter} onClear={() => setModelFilter("")} />
        {isLoading && <LoadingState />}

        {data && (
          <>
            <SessionTable
              sessions={filteredAndSorted}
              modelCosts={modelCosts}
              sortField={sortField}
              sortDirection={sortDirection}
              modelFilter={modelFilter}
              expandedSessionId={expandedSessionId}
              expandedSessionData={expandedSessionData}
              expandedEventsData={expandedEventsData}
              isLoadingDetails={isLoadingDetails}
              liveSessionIds={new Set<string>()}
              focusedRowIndex={focusedRowIndex}
              flashingSessionIds={new Set<string>()}
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
        </div>
      </main>
    </div>
  );
}
