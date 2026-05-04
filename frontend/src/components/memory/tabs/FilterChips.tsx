'use client'

import { Pin, Tag, X } from 'lucide-react'
import type {
  MemoryCategory,
  MemoryListResult,
  MemoryScope,
} from '@/lib/memory-api'
import { CATEGORY_CONFIG, SCOPE_CONFIG } from '@/lib/memory-config'
import { cn } from '@/lib/utils'

interface FilterChipsProps {
  pinnedOnly: boolean
  tagFilter: string | null
  scope?: MemoryScope
  category?: MemoryCategory
  isSearchMode: boolean
  searchQuery: string
  searchResults?: MemoryListResult
  onPinnedToggle: () => void
  onTagFilterChange: (tag: string | null) => void
  onScopeChange: (scope: MemoryScope | undefined) => void
  onCategoryChange: (category: MemoryCategory | undefined) => void
}

export function FilterChips({
  pinnedOnly,
  tagFilter,
  scope,
  category,
  isSearchMode,
  searchQuery,
  searchResults,
  onPinnedToggle,
  onTagFilterChange,
  onScopeChange,
  onCategoryChange,
}: FilterChipsProps) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <button
        onClick={onPinnedToggle}
        className={cn(
          'flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium border transition-colors',
          pinnedOnly
            ? 'bg-violet-500/10 border-violet-500/40 text-violet-400'
            : 'bg-slate-800 border-slate-700 text-slate-400 hover:text-slate-300 hover:border-slate-600',
        )}
      >
        <Pin className="h-3 w-3" />
        Pinned
      </button>
      {tagFilter && (
        <span className="flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-emerald-900/30 text-emerald-400 border border-emerald-500/40">
          <Tag className="h-3 w-3" />
          {tagFilter}
          <button
            onClick={() => onTagFilterChange(null)}
            className="p-0.5 rounded-full hover:bg-emerald-800/50"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      )}
      {scope && (
        <span className="flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-slate-800 text-slate-300 border border-slate-700">
          Scope: {SCOPE_CONFIG[scope].label}
          <button
            onClick={() => onScopeChange(undefined)}
            className="p-0.5 rounded-full hover:bg-slate-700"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      )}
      {category && (
        <span className="flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-slate-800 text-slate-300 border border-slate-700">
          {CATEGORY_CONFIG[category].icon} {CATEGORY_CONFIG[category].label}
          <button
            onClick={() => onCategoryChange(undefined)}
            className="p-0.5 rounded-full hover:bg-slate-700"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      )}
      {isSearchMode && searchResults && (
        <span className="text-xs text-slate-400">
          {searchResults.total} results for &quot;{searchQuery}&quot;
        </span>
      )}
    </div>
  )
}
