"use client";

import { Suspense, useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  Brain,
  Search,
  X,
  RefreshCw,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useMemory } from "@/hooks/use-memory";
import type {
  MemoryCategory,
  MemoryScope,
  MemorySortBy,
  MemoryEpisode,
} from "@/lib/memory-api";
import { type SortField, type SortDirection } from "@/components/memory/SortableHeader";
import { DeleteModal } from "@/components/memory/DeleteModal";
import { BulkToolbar } from "@/components/memory/BulkToolbar";
import { MemoryTable } from "@/components/memory/MemoryTable";
import { MemorySettingsModal } from "@/components/memory/MemorySettingsModal";
import {
  SCOPE_CONFIG,
  CATEGORY_CONFIG,
  REFRESH_OPTIONS,
  REFRESH_STORAGE_KEY,
  SORT_STORAGE_KEY,
  type RefreshInterval,
} from "@/lib/memory-config";

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffSecs < 10) return "just now";
  if (diffSecs < 60) return `${diffSecs}s`;
  if (diffMins < 60) return `${diffMins}m`;
  if (diffHours < 24) return `${diffHours}h`;
  if (diffDays < 7) return `${diffDays}d`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function MemoryPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tableRef = useRef<HTMLDivElement>(null);

  // URL-synced filter state
  const groupId = searchParams.get("group") || undefined;
  const scope = (searchParams.get("scope") as MemoryScope) || undefined;
  const category = (searchParams.get("category") as MemoryCategory) || undefined;
  const sortBy = (searchParams.get("sort") as MemorySortBy) || "created_at";

  // Local state
  const [refreshInterval, setRefreshInterval] = useState<RefreshInterval>(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [sortField, setSortField] = useState<SortField>("created_at");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [focusedRowIndex, setFocusedRowIndex] = useState<number>(-1);
  const [expandedMemoryId, setExpandedMemoryId] = useState<string | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  // Use the memory hook
  const {
    stats,
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

  // Auto-refresh effect
  useEffect(() => {
    if (refreshInterval === 0) return;
    const intervalId = setInterval(() => {
      setIsRefreshing(true);
      refresh();
      setTimeout(() => setIsRefreshing(false), 500);
    }, refreshInterval);
    return () => clearInterval(intervalId);
  }, [refreshInterval, refresh]);

  // URL param updates
  const updateParams = useCallback(
    (updates: Record<string, string | undefined>) => {
      const params = new URLSearchParams(searchParams.toString());
      Object.entries(updates).forEach(([key, value]) => {
        if (value === undefined) {
          params.delete(key);
        } else {
          params.set(key, value);
        }
      });
      router.push(`/memory?${params.toString()}`, { scroll: false });
    },
    [router, searchParams]
  );

  const handleScopeChange = useCallback(
    (newScope: MemoryScope | undefined) => updateParams({ scope: newScope }),
    [updateParams]
  );

  const handleCategoryChange = useCallback(
    (newCategory: MemoryCategory | undefined) => updateParams({ category: newCategory }),
    [updateParams]
  );

  const handleRefreshChange = useCallback((interval: RefreshInterval) => {
    setRefreshInterval(interval);
    localStorage.setItem(REFRESH_STORAGE_KEY, String(interval));
  }, []);

  const handleSort = useCallback(
    (field: SortField) => {
      const newDirection = sortField === field && sortDirection === "desc" ? "asc" : "desc";
      setSortField(field);
      setSortDirection(newDirection);
      localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify({ field, direction: newDirection }));
    },
    [sortField, sortDirection]
  );

  // Toggle row expansion
  const handleToggleExpand = useCallback((id: string) => {
    setExpandedMemoryId((prev) => (prev === id ? null : id));
  }, []);

  // Determine display items (search results or episodes)
  const isSearchMode = searchQuery.length >= 2;
  const displayItems = useMemo((): MemoryEpisode[] => {
    if (isSearchMode && searchResults) {
      return searchResults.results.map((r) => ({
        uuid: r.uuid,
        name: "",
        content: r.content,
        source: r.source,
        category: "coding_standard" as MemoryCategory,
        scope: "global" as MemoryScope,
        scope_id: null,
        source_description: "",
        created_at: r.created_at,
        valid_at: r.created_at,
        entities: r.facts || [],
        relevance_score: r.relevance_score,
        utility_score: undefined,
        loaded_count: undefined,
        referenced_count: undefined,
        success_count: undefined,
      }));
    }
    return episodes;
  }, [isSearchMode, searchResults, episodes]);

  // Sort items
  const sortedItems = useMemo(() => {
    const items = [...displayItems];
    items.sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "scope":
          cmp = (a.scope || "").localeCompare(b.scope || "");
          break;
        case "category":
          cmp = (a.category || "").localeCompare(b.category || "");
          break;
        case "content":
          cmp = a.content.localeCompare(b.content);
          break;
        case "created_at":
          cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
          break;
        case "utility":
          cmp = (a.utility_score || 0) - (b.utility_score || 0);
          break;
      }
      return sortDirection === "asc" ? cmp : -cmp;
    });
    return items;
  }, [displayItems, sortField, sortDirection]);

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!sortedItems.length) return;

      switch (e.key) {
        case "ArrowDown":
        case "j":
          e.preventDefault();
          setFocusedRowIndex((prev) => Math.min(prev + 1, sortedItems.length - 1));
          break;
        case "ArrowUp":
        case "k":
          e.preventDefault();
          setFocusedRowIndex((prev) => Math.max(prev - 1, 0));
          break;
        case "Enter":
        case " ":
          e.preventDefault();
          if (focusedRowIndex >= 0 && focusedRowIndex < sortedItems.length) {
            handleToggleExpand(sortedItems[focusedRowIndex].uuid);
          }
          break;
        case "Escape":
          e.preventDefault();
          setExpandedMemoryId(null);
          break;
      }
    },
    [sortedItems, focusedRowIndex, handleToggleExpand]
  );

  // Scroll-based load more
  const handleScroll = useCallback(() => {
    if (!tableRef.current || isFetchingMore || !hasMore || isSearchMode) return;
    const { scrollTop, scrollHeight, clientHeight } = tableRef.current;
    if (scrollHeight - scrollTop - clientHeight < 500) {
      loadMore();
    }
  }, [hasMore, isFetchingMore, loadMore, isSearchMode]);

  // Delete handlers
  const handleDeleteClick = useCallback((id: string) => {
    setPendingDeleteId(id);
    setShowDeleteModal(true);
  }, []);

  const handleBulkDeleteClick = useCallback(() => {
    setPendingDeleteId(null);
    setShowDeleteModal(true);
  }, []);

  const handleConfirmDelete = useCallback(async () => {
    if (pendingDeleteId) {
      await deleteOne(pendingDeleteId);
      if (expandedMemoryId === pendingDeleteId) {
        setExpandedMemoryId(null);
      }
    } else {
      await deleteSelected();
      setExpandedMemoryId(null);
    }
    setShowDeleteModal(false);
    setPendingDeleteId(null);
  }, [pendingDeleteId, deleteOne, deleteSelected, expandedMemoryId]);

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      {/* Sub-header: Search & Controls */}
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/80 space-y-3">
        <div className="flex items-center gap-3">
          {/* Search */}
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <input
              type="text"
              placeholder="Semantic search..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-9 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:border-emerald-500"
              data-testid="memory-search"
            />
            {searchQuery && !isSearching && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              >
                <X className="h-4 w-4" />
              </button>
            )}
            {isSearching && (
              <div className="absolute right-3 top-1/2 -translate-y-1/2">
                <div className="w-4 h-4 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
              </div>
            )}
          </div>

          {/* Auto-refresh */}
          <div className="flex items-center gap-1.5">
            <RefreshCw
              className={cn(
                "h-4 w-4",
                isRefreshing ? "animate-spin text-emerald-500" : "text-slate-400"
              )}
            />
            <select
              value={refreshInterval}
              onChange={(e) =>
                handleRefreshChange(parseInt(e.target.value, 10) as RefreshInterval)
              }
              className={cn(
                "px-2 py-1.5 rounded-md border text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500/40",
                refreshInterval > 0
                  ? "bg-emerald-50 dark:bg-emerald-900/30 border-emerald-300 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300"
                  : "bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700"
              )}
            >
              {REFRESH_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Settings Button */}
          <button
            onClick={() => setShowSettingsModal(true)}
            className="p-2 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 dark:text-slate-400 dark:hover:text-slate-200 transition-colors"
            title="Memory Settings"
          >
            <Settings className="h-5 w-5" />
          </button>
        </div>

        {/* Active Filters */}
        <div className="flex items-center gap-2 flex-wrap">
          {scope && (
            <span className="flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
              Scope: {SCOPE_CONFIG[scope].label}
              <button
                onClick={() => handleScopeChange(undefined)}
                className="p-0.5 rounded-full hover:bg-slate-200 dark:hover:bg-slate-700"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          )}
          {category && (
            <span className="flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
              {CATEGORY_CONFIG[category].icon} {CATEGORY_CONFIG[category].label}
              <button
                onClick={() => handleCategoryChange(undefined)}
                className="p-0.5 rounded-full hover:bg-slate-200 dark:hover:bg-slate-700"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          )}
          {isSearchMode && searchResults && (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {searchResults.count} results for "{searchQuery}"
            </span>
          )}
        </div>
      </div>

      {/* Error Display */}
      {(statsError || episodesError) && (
        <div className="px-4 py-2 bg-red-50 dark:bg-red-900/20 border-b border-red-200 dark:border-red-800">
          <p className="text-sm text-red-600 dark:text-red-400">
            Error: {statsError?.message || episodesError?.message}
          </p>
        </div>
      )}

      {/* Table */}
      <div
        ref={tableRef}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        onScroll={handleScroll}
        className="flex-1 overflow-auto focus:outline-none"
      >
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
          focusedRowIndex={focusedRowIndex}
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
          formatRelativeTime={formatRelativeTime}
        />
      </div>

      {/* Bulk Actions Toolbar */}
      <BulkToolbar
        selectedCount={selectedIds.size}
        onDelete={handleBulkDeleteClick}
        onExport={exportSelected}
        onClear={clearSelection}
        isDeleting={isDeleting}
      />

      {/* Delete Modal */}
      <DeleteModal
        isOpen={showDeleteModal}
        onClose={() => {
          setShowDeleteModal(false);
          setPendingDeleteId(null);
        }}
        onConfirm={handleConfirmDelete}
        count={pendingDeleteId ? 1 : selectedIds.size}
        isDeleting={isDeleting}
      />

      {/* Settings Modal */}
      <MemorySettingsModal
        isOpen={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
      />
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex h-[calc(100vh-56px)]">
      <div className="flex-1 p-4">
        <div className="animate-pulse space-y-4">
          <div className="h-10 bg-slate-200 dark:bg-slate-700 rounded-lg" />
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="h-12 bg-slate-200 dark:bg-slate-700 rounded" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function MemoryPage() {
  const { stats, isLoadingStats } = useMemory({});

  const categoryStats = useMemo(() => {
    if (!stats?.by_category) return [];
    return stats.by_category.slice(0, 4);
  }, [stats]);

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Page Header */}
      <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm">
        <div className="px-4 lg:px-6">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-emerald-100 dark:bg-emerald-900/30">
                  <Brain className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                </div>
                <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100 tracking-tight">
                  Memory
                </h1>
              </div>

              <div className="hidden sm:flex items-center gap-3 text-xs font-mono tabular-nums">
                <span className="text-slate-500 dark:text-slate-400">
                  {isLoadingStats ? "..." : stats?.total ?? 0} total
                </span>
                {categoryStats.length > 0 && (
                  <>
                    <span className="text-slate-300 dark:text-slate-600">|</span>
                    {categoryStats.map((cat) => (
                      <span
                        key={cat.category}
                        className={cn("flex items-center gap-1", CATEGORY_CONFIG[cat.category].color)}
                      >
                        {CATEGORY_CONFIG[cat.category].icon}
                        {cat.count}
                      </span>
                    ))}
                  </>
                )}
              </div>
            </div>

            <div className="hidden lg:flex items-center gap-2 text-[10px] text-slate-400">
              <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono">j/k</span>
              <span>navigate</span>
              <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono">Enter</span>
              <span>expand</span>
              <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono">Esc</span>
              <span>collapse</span>
            </div>
          </div>
        </div>
      </header>

      <Suspense fallback={<LoadingState />}>
        <MemoryPageContent />
      </Suspense>
    </div>
  );
}
