import { Download, Filter, Radio, Search, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { REFRESH_OPTIONS, type RefreshInterval } from './tableConfig'

interface TableControlsProps {
  searchQuery: string
  onSearchChange: (value: string) => void
  clientFilter: string | null
  onClientFilterChange: (value: string | null) => void
  uniqueClients: string[]
  refreshInterval: RefreshInterval
  onRefreshIntervalChange: (value: RefreshInterval) => void
  onExport: () => void
  isRefreshing: boolean
  sortedCount: number
  totalCount: number
  hasExportData: boolean
}

export function TableControls({
  searchQuery,
  onSearchChange,
  clientFilter,
  onClientFilterChange,
  uniqueClients,
  refreshInterval,
  onRefreshIntervalChange,
  onExport,
  isRefreshing,
  sortedCount,
  totalCount,
  hasExportData,
}: TableControlsProps) {
  return (
    <div className="px-4 py-3 border-b border-slate-800 space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search blocked requests..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full pl-9 pr-9 py-2 rounded-lg border border-slate-700 bg-slate-800/50 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500/40 focus:border-amber-500"
          />
          {searchQuery && (
            <button
              onClick={() => onSearchChange('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Client filter */}
        <div className="relative">
          <Filter className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
          <select
            value={clientFilter || ''}
            onChange={(e) => onClientFilterChange(e.target.value || null)}
            className={cn(
              'pl-9 pr-8 py-2 rounded-lg border text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 appearance-none cursor-pointer',
              clientFilter
                ? 'bg-amber-900/30 border-amber-700 text-amber-300'
                : 'bg-slate-800/50 border-slate-700 text-slate-300',
            )}
          >
            <option value="">All Clients</option>
            {uniqueClients.map((client) => (
              <option key={client} value={client}>
                {client === '<unknown>' ? 'UNKNOWN' : client}
              </option>
            ))}
          </select>
        </div>

        {/* Auto-refresh */}
        <div className="flex items-center gap-1.5">
          <Radio
            className={cn(
              'h-4 w-4',
              refreshInterval > 0
                ? 'text-amber-400 animate-pulse'
                : 'text-slate-500',
            )}
          />
          <select
            value={refreshInterval}
            onChange={(e) =>
              onRefreshIntervalChange(
                parseInt(e.target.value, 10) as RefreshInterval,
              )
            }
            className={cn(
              'px-2 py-1.5 rounded-md border text-xs focus:outline-none focus:ring-2 focus:ring-amber-500/40',
              refreshInterval > 0
                ? 'bg-amber-900/30 border-amber-700 text-amber-300'
                : 'bg-slate-800/50 border-slate-700 text-slate-400',
            )}
          >
            {REFRESH_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Export */}
        <button
          onClick={onExport}
          disabled={!hasExportData}
          className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm transition-colors"
        >
          <Download className="w-4 h-4" />
          Export
        </button>

        {/* Refresh indicator */}
        {isRefreshing && (
          <div className="flex items-center gap-2 text-xs text-amber-400">
            <div className="w-3 h-3 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
            Refreshing...
          </div>
        )}
      </div>

      {/* Active filters display */}
      {(clientFilter || searchQuery) && (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">
            Showing {sortedCount} of {totalCount}
          </span>
          {clientFilter && (
            <span
              className={cn(
                'flex items-center gap-1 px-2 py-1 rounded-full border',
                clientFilter === '<unknown>'
                  ? 'bg-red-900/30 text-red-300 border-red-700'
                  : 'bg-amber-900/30 text-amber-300 border-amber-700',
              )}
            >
              Client: {clientFilter === '<unknown>' ? 'UNKNOWN' : clientFilter}
              <button
                onClick={() => onClientFilterChange(null)}
                className="hover:text-slate-100"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          )}
        </div>
      )}
    </div>
  )
}
