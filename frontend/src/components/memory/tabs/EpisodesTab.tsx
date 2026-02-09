"use client";

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { cn } from "@/lib/utils";
import { useMemory } from "@/hooks/use-memory";
import { useEpisodesFilters } from "@/hooks/use-episodes-filters";
import { useEpisodesActions } from "@/hooks/use-episodes-actions";
import { useUrlParams } from "@/hooks/use-url-params";
import type { MemoryCategory, MemoryScope, MemorySortBy } from "@/lib/memory-api";
import type { SortField } from "@/components/memory/SortableHeader";
import { DeleteModal } from "@/components/memory/DeleteModal";
import { BulkToolbar } from "@/components/memory/BulkToolbar";
import { MemoryTable } from "@/components/memory/MemoryTable";
import { MemorySettingsModal } from "@/components/memory/MemorySettingsModal";
import { EpisodesTimelineView } from "@/components/memory/EpisodesTimelineView";
import { EpisodesToolbar } from "./EpisodesToolbar";
import { FilterChips } from "./FilterChips";
import { formatRelativeTime } from "@/lib/format-utils";
import { SORT_STORAGE_KEY, SEARCH_STORAGE_KEY } from "@/lib/memory-config";

type EpisodesViewMode = "table" | "timeline";
const VIEW_MODE_KEY = "memory-episodes-view";

export function EpisodesTab() {
  const searchParams = useSearchParams();
  const tableRef = useRef<HTMLDivElement>(null);

  const groupId = searchParams.get("group") || undefined;
  const scope = (searchParams.get("scope") as MemoryScope) || undefined;
  const category = (searchParams.get("category") as MemoryCategory) || undefined;
  const sortBy = (searchParams.get("sort") as MemorySortBy) || "created_at";

  const [viewMode, setViewMode] = useState<EpisodesViewMode>(() => {
    try {
      const stored = localStorage.getItem(VIEW_MODE_KEY);
      return stored === "timeline" ? "timeline" : "table";
    } catch {
      return "table";
    }
  });
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [showSettingsModal, setShowSettingsModal] = useState(false);

  const {
    episodes,
    searchResults,
    hasMore,
    loadMore,
    isFetchingMore,
    isLoadingEpisodes,
    isSearching,
    selectedIds,
    toggleSelect,
    selectAll,
    clearSelection,
    isAllSelected,
    searchQuery,
    setSearchQuery,
    deleteOne,
    deleteSelected,
    exportSelected,
    isDeleting,
    refresh,
    statsError,
    episodesError,
  } = useMemory({ groupId, scope, category, sortBy });

  const isSearchMode = searchQuery.length >= 2;
  const displayItems = useMemo(() => {
    if (isSearchMode && searchResults) {
      return searchResults.episodes;
    }
    return episodes;
  }, [isSearchMode, searchResults, episodes]);

  const {
    sortField,
    setSortField,
    sortDirection,
    setSortDirection,
    pinnedOnly,
    setPinnedOnly,
    tagFilter,
    setTagFilter,
    sortedItems,
  } = useEpisodesFilters({ displayItems });

  const {
    showDeleteModal,
    pendingDeleteId,
    expandedMemoryId,
    handleDeleteClick,
    handleBulkDeleteClick,
    handleBulkTierChange,
    handleBulkTag,
    handleConfirmDelete,
    handleToggleExpand,
    closeDeleteModal,
  } = useEpisodesActions({ deleteOne, deleteSelected, exportSelected, refresh, isDeleting });

  const { handleScopeChange, handleCategoryChange } = useUrlParams();

  useEffect(() => {
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
    const storedSearch = localStorage.getItem(SEARCH_STORAGE_KEY);
    if (storedSearch) {
      setSearchQuery(storedSearch);
    }
  }, [setSearchQuery, setSortField, setSortDirection]);

  const handleRefresh = useCallback(() => {
    setIsRefreshing(true);
    refresh();
    setTimeout(() => setIsRefreshing(false), 500);
  }, [refresh]);

  const handleSort = useCallback(
    (field: SortField) => {
      const newDirection = sortField === field && sortDirection === "desc" ? "asc" : "desc";
      setSortField(field);
      setSortDirection(newDirection);
      localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify({ field, direction: newDirection }));
    },
    [sortField, sortDirection, setSortField, setSortDirection]
  );

  const handleTierChange = useCallback(
    (_id: string, _newCategory: MemoryCategory) => {
      refresh();
    },
    [refresh]
  );

  const handleScroll = useCallback(() => {
    if (!tableRef.current || isFetchingMore || !hasMore || isSearchMode) return;
    const { scrollTop, scrollHeight, clientHeight } = tableRef.current;
    if (scrollHeight - scrollTop - clientHeight < 500) {
      loadMore();
    }
  }, [hasMore, isFetchingMore, loadMore, isSearchMode]);

  const handleViewModeChange = useCallback((mode: EpisodesViewMode) => {
    setViewMode(mode);
    localStorage.setItem(VIEW_MODE_KEY, mode);
  }, []);

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80 space-y-3">
        <EpisodesToolbar
          searchQuery={searchQuery}
          isSearching={isSearching}
          viewMode={viewMode}
          isRefreshing={isRefreshing}
          onSearchChange={setSearchQuery}
          onViewModeChange={handleViewModeChange}
          onRefresh={handleRefresh}
          onSettingsClick={() => setShowSettingsModal(true)}
        />

        <FilterChips
          pinnedOnly={pinnedOnly}
          tagFilter={tagFilter}
          scope={scope}
          category={category}
          isSearchMode={isSearchMode}
          searchQuery={searchQuery}
          searchResults={searchResults}
          onPinnedToggle={() => setPinnedOnly(!pinnedOnly)}
          onTagFilterChange={setTagFilter}
          onScopeChange={handleScopeChange}
          onCategoryChange={handleCategoryChange}
        />
      </div>

      {(statsError || episodesError) && (
        <div className="px-4 py-2 bg-red-900/20 border-b border-red-800">
          <p className="text-sm text-red-400">
            Error: {statsError?.message || episodesError?.message}
          </p>
        </div>
      )}

      <div
        ref={tableRef}
        onScroll={handleScroll}
        className={cn("flex-1 overflow-auto", viewMode === "table" && selectedIds.size > 0 && "pb-16")}
      >
        {viewMode === "table" ? (
          <MemoryTable
            items={sortedItems}
            isLoading={isLoadingEpisodes}
            isFetchingMore={isFetchingMore}
            isSearchMode={isSearchMode}
            searchQuery={searchQuery}
            sortField={sortField}
            sortDirection={sortDirection}
            selectedIds={selectedIds}
            isAllSelected={isAllSelected}
            expandedMemoryId={expandedMemoryId}
            scope={scope}
            category={category}
            pendingDeleteId={pendingDeleteId}
            isDeleting={isDeleting}
            onSort={handleSort}
            onSelectAll={selectAll}
            onClearSelection={clearSelection}
            onToggleExpand={handleToggleExpand}
            onToggleSelect={toggleSelect}
            onScopeChange={handleScopeChange}
            onCategoryChange={handleCategoryChange}
            onDelete={handleDeleteClick}
            onTierChange={handleTierChange}
            onEdit={refresh}
            onTagFilter={setTagFilter}
            formatRelativeTime={formatRelativeTime}
          />
        ) : (
          <EpisodesTimelineView
            items={sortedItems}
            isLoading={isLoadingEpisodes}
            isFetchingMore={isFetchingMore}
          />
        )}
      </div>

      {viewMode === "table" && (
        <BulkToolbar
          selectedCount={selectedIds.size}
          selectedIds={selectedIds}
          onDelete={handleBulkDeleteClick}
          onExport={exportSelected}
          onClear={clearSelection}
          onTierChange={handleBulkTierChange}
          onBulkTag={handleBulkTag}
          isDeleting={isDeleting}
        />
      )}

      <DeleteModal
        isOpen={showDeleteModal}
        onClose={closeDeleteModal}
        onConfirm={handleConfirmDelete}
        count={pendingDeleteId ? 1 : selectedIds.size}
        isDeleting={isDeleting}
      />

      <MemorySettingsModal
        isOpen={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
      />
    </div>
  );
}
