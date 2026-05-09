import { ArrowUpDown } from 'lucide-react'
import type { TopMemory } from '@/lib/memory-api'
import { cn } from '@/lib/utils'
import { EmptyChart } from '../analytics-components'

interface TopMemoriesTableProps {
  data: TopMemory[]
  sortBy: string
  onSortChange: (field: string) => void
  onRowClick?: (uuid: string) => void
}

const SORT_OPTIONS = [
  { field: 'utility_score', label: 'Utility' },
  { field: 'referenced_count', label: 'Citations' },
  { field: 'lifecycle_score', label: 'Lifecycle' },
] as const

const TIER_DOT_COLORS: Record<string, string> = {
  mandate: 'bg-red-500',
  guardrail: 'bg-amber-500',
  reference: 'bg-blue-500',
  archive: 'bg-slate-500',
}

export function TopMemoriesTable({
  data,
  sortBy,
  onSortChange,
  onRowClick,
}: TopMemoriesTableProps) {
  if (data.length === 0)
    return <EmptyChart label="No memories with usage data" />

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5">
        <ArrowUpDown className="h-3 w-3 text-slate-500" />
        {SORT_OPTIONS.map((opt) => (
          <button
            key={opt.field}
            onClick={() => onSortChange(opt.field)}
            className={cn(
              'px-2 py-0.5 text-[10px] font-medium rounded transition-colors',
              sortBy === opt.field
                ? 'bg-purple-600/30 text-purple-300'
                : 'text-slate-500 hover:text-slate-300',
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>
      <div className="space-y-1">
        {data.map((mem) => (
          <button
            key={mem.uuid}
            onClick={() => onRowClick?.(mem.uuid)}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md bg-slate-800/30 hover:bg-slate-800/60 transition-colors text-left group"
          >
            <span
              className={cn(
                'w-1.5 h-1.5 rounded-full shrink-0',
                TIER_DOT_COLORS[mem.injection_tier] ?? 'bg-slate-500',
              )}
            />
            <span className="text-xs text-slate-300 truncate flex-1 min-w-0">
              {mem.content}
            </span>
            {mem.lifecycle_score != null && (
              <span
                className={cn(
                  'text-[9px] font-mono shrink-0 tabular-nums px-1 py-0.5 rounded',
                  mem.lifecycle_score >= 0.7
                    ? 'text-emerald-400 bg-emerald-500/10'
                    : mem.lifecycle_score >= 0.4
                      ? 'text-amber-400 bg-amber-500/10'
                      : 'text-slate-500 bg-slate-800/50',
                )}
              >
                {(mem.lifecycle_score * 100).toFixed(0)}
              </span>
            )}
            <span className="text-[10px] font-mono text-slate-500 shrink-0 tabular-nums">
              {mem.utility_score.toFixed(1)}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
