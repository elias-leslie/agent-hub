"use client";

import { Suspense, useState, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Brain } from "lucide-react";
import { useMemory } from "@/hooks/use-memory";
import { MemoryStats } from "@/components/memory/memory-stats";
import { MemoryFilters } from "@/components/memory/memory-filters";
import { MemoryList } from "@/components/memory/memory-list";
import { BulkActionsToolbar } from "@/components/memory/bulk-actions-toolbar";
import { DeleteConfirmationModal } from "@/components/memory/delete-confirmation-modal";
import type { MemoryCategory, MemoryScope, MemorySortBy } from "@/lib/memory-api";

function MemoryPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // URL-synced filter state
  const groupId = searchParams.get("group") || undefined;
  const scope = (searchParams.get("scope") as MemoryScope) || undefined;
  const category = (searchParams.get("category") as MemoryCategory) || undefined;
  const sortBy = (searchParams.get("sort") as MemorySortBy) || "created_at";

  // Modal state
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  // Use the memory hook
  const {
    stats,
    groups,
    episodes,
    searchResults,
    hasMore,
    loadMore,
    isFetchingMore,
    isLoadingStats,
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
  } = useMemory({ groupId, scope, category, sortBy });

  // Update URL params
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
    [router, searchParams],
  );

  // Filter handlers synced to URL
  const handleGroupChange = useCallback(
    (newGroupId: string | undefined) => {
      updateParams({ group: newGroupId });
    },
    [updateParams],
  );

  const handleScopeChange = useCallback(
    (newScope: MemoryScope | undefined) => {
      updateParams({ scope: newScope });
    },
    [updateParams],
  );

  const handleCategoryChange = useCallback(
    (newCategory: MemoryCategory | undefined) => {
      updateParams({ category: newCategory });
    },
    [updateParams],
  );

  const handleSortChange = useCallback(
    (newSortBy: MemorySortBy) => {
      updateParams({ sort: newSortBy });
    },
    [updateParams],
  );

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
    } else {
      await deleteSelected();
    }
    setShowDeleteModal(false);
    setPendingDeleteId(null);
  }, [pendingDeleteId, deleteOne, deleteSelected]);

  const handleCloseModal = useCallback(() => {
    setShowDeleteModal(false);
    setPendingDeleteId(null);
  }, []);

  // Determine which episodes to display (search results or list)
  // Search results have different shape, convert to episode format
  const displayEpisodes =
    searchQuery.length >= 2 && searchResults
      ? searchResults.results.map((r) => ({
          uuid: r.uuid,
          name: "",
          content: r.content,
          source: r.source,
          category: "coding_standard" as const,
          scope: "global" as const,
          scope_id: null,
          source_description: "",
          created_at: r.created_at,
          valid_at: r.created_at,
          entities: [],
        }))
      : episodes;

  return (
    <>
      <main className="px-6 lg:px-8 py-8 space-y-6">
        {/* Stats KPIs */}
        <MemoryStats stats={stats} isLoading={isLoadingStats} />

        {/* Filters and Search */}
        <MemoryFilters
          groups={groups}
          selectedGroup={groupId}
          onGroupChange={handleGroupChange}
          selectedScope={scope}
          onScopeChange={handleScopeChange}
          selectedCategory={category}
          onCategoryChange={handleCategoryChange}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          isSearching={isSearching}
          sortBy={sortBy}
          onSortChange={handleSortChange}
        />

        {/* Memory List */}
        <MemoryList
          episodes={displayEpisodes}
          isLoading={isLoadingEpisodes}
          hasMore={hasMore}
          onLoadMore={loadMore}
          isFetchingMore={isFetchingMore}
          selectedIds={selectedIds}
          onToggleSelect={toggleSelect}
          onSelectAll={selectAll}
          onClearSelection={clearSelection}
          isAllSelected={isAllSelected}
          onDelete={handleDeleteClick}
          isDeleting={isDeleting}
        />
      </main>

      {/* Bulk Actions Toolbar */}
      <BulkActionsToolbar
        selectedCount={selectedIds.size}
        onDelete={handleBulkDeleteClick}
        onExport={exportSelected}
        onClearSelection={clearSelection}
        isDeleting={isDeleting}
      />

      {/* Delete Confirmation Modal */}
      <DeleteConfirmationModal
        isOpen={showDeleteModal}
        onClose={handleCloseModal}
        onConfirm={handleConfirmDelete}
        count={pendingDeleteId ? 1 : selectedIds.size}
        isDeleting={isDeleting}
      />
    </>
  );
}

function LoadingState() {
  return (
    <main className="px-6 lg:px-8 py-8 space-y-6">
      {/* Stats skeleton */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div
            key={i}
            className="border-l-4 border-l-slate-300 dark:border-l-slate-700 rounded-lg p-4 bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800"
          >
            <div className="animate-pulse">
              <div className="h-4 w-20 bg-slate-200 dark:bg-slate-700 rounded" />
              <div className="h-8 w-16 bg-slate-200 dark:bg-slate-700 rounded mt-2" />
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}

export default function MemoryPage() {
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Page Header */}
      <header className="sticky top-0 z-10 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-emerald-100 dark:bg-emerald-900/30">
                <Brain className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
              </div>
              <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                Memory
              </h1>
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
