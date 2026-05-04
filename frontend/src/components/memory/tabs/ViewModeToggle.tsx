'use client'

import { Clock, List } from 'lucide-react'
import { cn } from '@/lib/utils'

type EpisodesViewMode = 'table' | 'timeline'

interface ViewModeToggleProps {
  viewMode: EpisodesViewMode
  onViewModeChange: (mode: EpisodesViewMode) => void
}

export function ViewModeToggle({
  viewMode,
  onViewModeChange,
}: ViewModeToggleProps) {
  return (
    <div className="flex items-center rounded-lg border border-slate-700 bg-slate-800">
      <button
        onClick={() => onViewModeChange('table')}
        className={cn(
          'p-1.5 rounded-md transition-colors',
          viewMode === 'table'
            ? 'bg-slate-700 text-emerald-400'
            : 'text-slate-400 hover:text-slate-200',
        )}
        title="Table view"
      >
        <List className="h-4 w-4" />
      </button>
      <button
        onClick={() => onViewModeChange('timeline')}
        className={cn(
          'p-1.5 rounded-md transition-colors',
          viewMode === 'timeline'
            ? 'bg-slate-700 text-emerald-400'
            : 'text-slate-400 hover:text-slate-200',
        )}
        title="Timeline view"
      >
        <Clock className="h-4 w-4" />
      </button>
    </div>
  )
}
