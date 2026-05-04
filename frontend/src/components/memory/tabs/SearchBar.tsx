'use client'

import { Search, X } from 'lucide-react'
import { SEARCH_STORAGE_KEY } from '@/lib/memory-config'

interface SearchBarProps {
  searchQuery: string
  isSearching: boolean
  onSearchChange: (query: string) => void
}

export function SearchBar({
  searchQuery,
  isSearching,
  onSearchChange,
}: SearchBarProps) {
  const handleChange = (value: string) => {
    onSearchChange(value)
    if (value) {
      localStorage.setItem(SEARCH_STORAGE_KEY, value)
    } else {
      localStorage.removeItem(SEARCH_STORAGE_KEY)
    }
  }

  const handleClear = () => {
    onSearchChange('')
    localStorage.removeItem(SEARCH_STORAGE_KEY)
  }

  return (
    <div className="relative flex-1 max-w-md">
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
      <input
        type="text"
        placeholder="Search..."
        value={searchQuery}
        onChange={(e) => handleChange(e.target.value)}
        className="w-full pl-9 pr-9 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:border-emerald-500"
        data-testid="memory-search"
      />
      {searchQuery && !isSearching && (
        <button
          onClick={handleClear}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
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
  )
}
