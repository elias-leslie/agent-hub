'use client'

import { RefreshCw, Settings } from 'lucide-react'
import { cn } from '@/lib/utils'
import { SearchBar } from './SearchBar'
import { ViewModeToggle } from './ViewModeToggle'

type EpisodesViewMode = 'table' | 'timeline'

interface EpisodesToolbarProps {
  searchQuery: string
  isSearching: boolean
  viewMode: EpisodesViewMode
  isRefreshing: boolean
  onSearchChange: (query: string) => void
  onViewModeChange: (mode: EpisodesViewMode) => void
  onRefresh: () => void
  onSettingsClick: () => void
}

export function EpisodesToolbar({
  searchQuery,
  isSearching,
  viewMode,
  isRefreshing,
  onSearchChange,
  onViewModeChange,
  onRefresh,
  onSettingsClick,
}: EpisodesToolbarProps) {
  return (
    <div className="flex items-center gap-3">
      <SearchBar
        searchQuery={searchQuery}
        isSearching={isSearching}
        onSearchChange={onSearchChange}
      />

      <ViewModeToggle viewMode={viewMode} onViewModeChange={onViewModeChange} />

      <button
        onClick={onRefresh}
        disabled={isRefreshing}
        className={cn(
          'p-2 rounded-lg transition-colors',
          'text-slate-400 hover:text-slate-200 hover:bg-slate-800',
          isRefreshing && 'cursor-not-allowed',
        )}
        title="Refresh"
      >
        <RefreshCw
          className={cn(
            'h-4 w-4',
            isRefreshing && 'animate-spin text-emerald-500',
          )}
        />
      </button>

      <button
        onClick={onSettingsClick}
        className="p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
        title="Memory Settings"
      >
        <Settings className="h-5 w-5" />
      </button>
    </div>
  )
}
