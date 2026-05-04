'use client'

import { useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BulkToolbar } from '@/components/memory/BulkToolbar'
import { DeleteModal } from '@/components/memory/DeleteModal'
import { EpisodesTimelineView } from '@/components/memory/EpisodesTimelineView'
import { MemorySettingsModal } from '@/components/memory/MemorySettingsModal'
import { MemoryTable } from '@/components/memory/MemoryTable'
import type { SortField } from '@/components/memory/types'
import { useEpisodesActions } from '@/hooks/use-episodes-actions'
import { useEpisodesFilters } from '@/hooks/use-episodes-filters'
import { useMemory } from '@/hooks/use-memory'
import { useUrlParams } from '@/hooks/use-url-params'
import { formatRelativeTime } from '@/lib/formatters'
import type {
  MemoryCategory,
  MemoryScope,
  MemorySortBy,
} from '@/lib/memory-api'
import { SEARCH_STORAGE_KEY, SORT_STORAGE_KEY } from '@/lib/memory-config'
import { cn } from '@/lib/utils'
import { EpisodesToolbar } from './EpisodesToolbar'
import { FilterChips } from './FilterChips'

type EpisodesViewMode = 'table' | 'timeline'
const VIEW_MODE_KEY = 'memory-episodes-view'

export function EpisodesTab() {
  const searchParams = useSearchParams()
  const tableRef = useRef<HTMLDivElement>(null)

  const groupId = searchParams.get('group') || undefined
  const scope = (searchParams.get('scope') as MemoryScope) || undefined
  const category = (searchParams.get('category') as MemoryCategory) || undefined
  const sortBy = (searchParams.get('sort') as MemorySortBy) || 'updated_at'

  const [viewMode, setViewMode] = useState<EpisodesViewMode>(() => {
    try {
      const stored = localStorage.getItem(VIEW_MODE_KEY)
      return stored === 'timeline' ? 'timeline' : 'table'
    } catch {
      return 'table'
    }
  })
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [showSettingsModal, setShowSettingsModal] = useState(false)

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
  } = useMemory({ groupId, scope, category, sortBy })

  const isSearchMode = searchQuery.length >= 2
  const displayItems = useMemo(() => {
    if (isSearchMode && searchResults) {
      return searchResults.episodes
    }
    return episodes
  }, [isSearchMode, searchResults, episodes])

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
  } = useEpisodesFilters({ displayItems })

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
  } = useEpisodesActions({
    deleteOne,
    deleteSelected,
    refresh,
    isDeleting,
  })

  const { handleScopeChange, handleCategoryChange } = useUrlParams()

  useEffect(() => {
    const storedSort = localStorage.getItem(SORT_STORAGE_KEY)
    if (storedSort) {
      try {
        const { field, direction } = JSON.parse(storedSort)
        setSortField(field)
        setSortDirection(direction)
      } catch {
        // ignore
      }
    }
    const storedSearch = localStorage.getItem(SEARCH_STORAGE_KEY)
    if (storedSearch) {
      setSearchQuery(storedSearch)
    }
  }, [setSearchQuery, setSortField, setSortDirection])

  const handleRefresh = useCallback(() => {
    setIsRefreshing(true)
    refresh()
    setTimeout(() => setIsRefreshing(false), 500)
  }, [refresh])

  const handleSort = useCallback(
    (field: SortField) => {
      const newDirection =
        sortField === field && sortDirection === 'desc' ? 'asc' : 'desc'
      setSortField(field)
      setSortDirection(newDirection)
      localStorage.setItem(
        SORT_STORAGE_KEY,
        JSON.stringify({ field, direction: newDirection }),
      )
    },
    [sortField, sortDirection, setSortField, setSortDirection],
  )

  const handleTierChange = useCallback(
    (_id: string, _newCategory: MemoryCategory) => {
      refresh()
    },
    [refresh],
  )

  const handleScroll = useCallback(() => {
    if (!tableRef.current || isFetchingMore || !hasMore || isSearchMode) return
    const { scrollTop, scrollHeight, clientHeight } = tableRef.current
    if (scrollHeight - scrollTop - clientHeight < 500) {
      loadMore()
    }
  }, [hasMore, isFetchingMore, loadMore, isSearchMode])

  const handleViewModeChange = useCallback((mode: EpisodesViewMode) => {
    setViewMode(mode)
    localStorage.setItem(VIEW_MODE_KEY, mode)
  }, [])

  // Client-side sorts need the full dataset; backend pages are newest-first.
  // Therefore updated_at DESC is stable with pagination, but other orders are not.
  const shouldPrefetchAllPages =
    !isSearchMode && (sortField !== 'updated_at' || sortDirection === 'asc')
  useEffect(() => {
    if (
      !shouldPrefetchAllPages ||
      !hasMore ||
      isFetchingMore ||
      isLoadingEpisodes
    ) {
      return
    }
    loadMore()
  }, [
    shouldPrefetchAllPages,
    hasMore,
    isFetchingMore,
    isLoadingEpisodes,
    loadMore,
  ])

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
        className={cn(
          'flex-1 overflow-auto',
          viewMode === 'table' && selectedIds.size > 0 && 'pb-16',
        )}
      >
        {viewMode === 'table' ? (
          <MemoryTable
            items={sortedItems}
            isLoading={isLoadingEpisodes || (shouldPrefetchAllPages && hasMore)}
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

      {viewMode === 'table' && (
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
  )
}
