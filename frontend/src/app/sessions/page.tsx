"use client";

import { useState, useCallback, useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useModels } from "@/components/chat/use-models";
import { buildModelCostMap } from "@/lib/model-pricing";
import { SessionTable } from "./components/SessionTable";
import { SessionsHeader } from "./components/SessionsHeader";
import { LoadingState } from "./components/LoadingState";
import { InfiniteScrollFooter } from "./components/InfiniteScrollFooter";
import { ErrorAlert } from "./components/ErrorAlert";
import { EmptyState } from "./components/EmptyState";
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

  const { sortField, sortDirection, handleSort } = useSessionPreferences();

  const {
    data,
    allSessions,
    loadedCount,
    total,
    isLoading,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useSessionsData({ statusFilter, projectFilter: "", pageSize });

  const {
    modelFilter,
    setModelFilter,
    searchQuery,
    setSearchQuery,
    hiddenBenchmarkCount,
    filteredAndSorted,
    visibleCount,
  } = useSessionFilters({
    sessions: allSessions,
    modelCosts,
    sortField,
    sortDirection,
    hideBenchmarkTraffic,
  });

  const {
    expandedSessionId,
    expandedSessionData,
    expandedEventsData,
    isLoadingDetails,
    handleToggleExpand,
    clearExpansion,
  } = useSessionExpansion();

  const { focusedRowIndex, handleKeyDown } = useSessionKeyboard({
    sessions: filteredAndSorted,
    onToggleExpand: handleToggleExpand,
    onClearExpansion: clearExpansion,
  });

  const liveSessionIds = useMemo(
    () =>
      new Set(
        allSessions
          .filter((session) => session.status === "active" || session.live_activity?.lifecycle_state === "working")
          .map((session) => session.id),
      ),
    [allSessions],
  );

  const handleRefresh = useCallback(() => {
    setIsRefreshing(true);
    queryClient.invalidateQueries({ queryKey: ["sessions"] }).finally(() => {
      setTimeout(() => setIsRefreshing(false), 500);
    });
  }, [queryClient]);

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

  const counts = useMemo(
    () => ({ visible: visibleCount, loaded: loadedCount, total }),
    [loadedCount, total, visibleCount],
  );

  const showEmptyData = Boolean(data && !error && !isLoading && total === 0);
  const showNoMatch = Boolean(data && !error && !isLoading && total > 0 && visibleCount === 0);
  const showTable = Boolean(data && !error && !isLoading && visibleCount > 0);

  return (
    <div className="page-shell bg-slate-950 text-slate-100">
      <div className="page-backdrop bg-slate-950/90" />
      <SessionsHeader
        counts={counts}
        searchQuery={searchQuery}
        statusFilter={statusFilter}
        hideBenchmarkTraffic={hideBenchmarkTraffic}
        hiddenBenchmarkCount={hiddenBenchmarkCount}
        isRefreshing={isRefreshing}
        modelFilter={modelFilter}
        onSearchChange={setSearchQuery}
        onStatusFilterChange={setStatusFilter}
        onHideBenchmarkTrafficChange={setHideBenchmarkTraffic}
        onClearModelFilter={() => setModelFilter("")}
        onRefresh={handleRefresh}
      />

      <main className="page-frame">
        <div className="page-container space-y-4">
          {error && <ErrorAlert error={error} onRetry={handleRefresh} />}

          {isLoading && <LoadingState />}
          {showEmptyData && <EmptyState kind="no-data" />}
          {showNoMatch && <EmptyState kind="no-match" />}

          {showTable && (
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
                liveSessionIds={liveSessionIds}
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
                hasNextPage={Boolean(hasNextPage)}
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
