import { RefreshCw, Search } from 'lucide-react'
import type { RefObject } from 'react'

import { cn } from '@/lib/utils'
import type { SessionsCountTriplet } from '../types'
import { ModelFilterBadge } from './ModelFilterBadge'

const COUNT_FORMATTER = new Intl.NumberFormat('en-US')

export function SessionsHeader({
  counts,
  searchQuery,
  statusFilter,
  hideBenchmarkTraffic,
  hiddenBenchmarkCount,
  isRefreshing,
  modelFilter,
  searchInputRef,
  onSearchChange,
  onStatusFilterChange,
  onHideBenchmarkTrafficChange,
  onClearModelFilter,
  onRefresh,
}: {
  counts: SessionsCountTriplet
  searchQuery: string
  statusFilter: string
  hideBenchmarkTraffic: boolean
  hiddenBenchmarkCount: number
  isRefreshing: boolean
  modelFilter: string
  searchInputRef?: RefObject<HTMLInputElement | null>
  onSearchChange: (value: string) => void
  onStatusFilterChange: (value: string) => void
  onHideBenchmarkTrafficChange: (value: boolean) => void
  onClearModelFilter: () => void
  onRefresh: () => void
}) {
  const formattedVisible = COUNT_FORMATTER.format(counts.visible)
  const formattedLoaded = COUNT_FORMATTER.format(counts.loaded)
  const formattedTotal = COUNT_FORMATTER.format(counts.total)

  return (
    <header className="page-header border-b border-slate-800/60 bg-slate-950/92">
      <div className="page-container px-4 lg:px-8">
        <div className="flex flex-col gap-2.5 py-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0 space-y-1.5">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-base font-semibold tracking-tight text-slate-100">
                Sessions
              </h1>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-[13px] text-slate-400">
              <span
                data-testid="sessions-filter-scope"
                className="inline-flex flex-wrap items-center gap-1.5"
              >
                <span className="text-slate-300">
                  <span data-testid="sessions-visible-count">
                    {formattedVisible}
                  </span>{' '}
                  visible
                </span>
                <span className="text-slate-700">·</span>
                <span>
                  <span data-testid="sessions-loaded-count">
                    {formattedLoaded}
                  </span>{' '}
                  loaded
                </span>
                <span className="text-slate-700">·</span>
                <span>
                  <span data-testid="sessions-total-count">
                    {formattedTotal}
                  </span>{' '}
                  total
                </span>
              </span>
              {modelFilter ? (
                <ModelFilterBadge
                  modelFilter={modelFilter}
                  onClear={onClearModelFilter}
                />
              ) : null}
            </div>
          </div>

          <div className="flex w-full flex-col gap-2.5 xl:max-w-2xl xl:flex-row xl:items-center xl:justify-end">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-3 w-3 -translate-y-1/2 text-slate-500" />
              <input
                ref={searchInputRef}
                type="text"
                placeholder="Search loaded rows…"
                value={searchQuery}
                onChange={(e) => onSearchChange(e.target.value)}
                className="control-input w-full border-slate-800/70 bg-slate-950/35 py-1.5 pl-9 text-[13px] placeholder:text-slate-500"
              />
            </div>

            <select
              data-testid="filter-status"
              value={statusFilter}
              onChange={(e) => onStatusFilterChange(e.target.value)}
              className="control-select min-w-[7.5rem] cursor-pointer border-slate-800/70 bg-slate-950/55 py-1.5 text-[13px]"
            >
              <option value="">All statuses</option>
              <option value="active">Active</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
            </select>

            <button
              type="button"
              data-testid="toggle-benchmark-traffic"
              onClick={() =>
                onHideBenchmarkTrafficChange(!hideBenchmarkTraffic)
              }
              className={cn(
                'rounded-md border px-2.5 py-1.5 text-[11px] font-medium transition-colors',
                hideBenchmarkTraffic
                  ? 'border-slate-800/80 bg-slate-950/45 text-slate-400 hover:border-slate-700 hover:text-slate-200'
                  : 'border-slate-800/70 bg-slate-950/55 text-slate-400 hover:border-slate-700 hover:bg-slate-900/60 hover:text-slate-200',
              )}
            >
              {hideBenchmarkTraffic ? 'Benchmarks hidden' : 'Benchmarks shown'}
              {hiddenBenchmarkCount > 0 ? ` · ${hiddenBenchmarkCount}` : ''}
            </button>

            <button
              type="button"
              onClick={onRefresh}
              aria-label="Refresh"
              title="Refresh"
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-800/70 bg-slate-950/35 text-slate-400 transition-colors hover:border-slate-700 hover:bg-slate-900/55 hover:text-slate-100"
            >
              <RefreshCw
                className={cn(
                  'h-3 w-3',
                  isRefreshing && 'animate-spin text-amber-300',
                )}
              />
            </button>
          </div>
        </div>
      </div>
    </header>
  )
}
