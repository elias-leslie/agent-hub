import { Shield } from 'lucide-react'
import { useRef } from 'react'
import { SortableHeader } from '@/components/ui/SortableHeader'
import type { BlockedRequest } from '@/lib/api'
import { BlockedRequestRow } from './BlockedRequestRow'
import { TableControls } from './TableControls'
import { TABLE_GRID_COLS } from './tableConfig'
import { useBlockedRequestsTable } from './useBlockedRequestsTable'

export function BlockedRequestsTable({
  requests,
  isLoading,
  onRefresh,
  isRefreshing,
}: {
  requests: BlockedRequest[]
  isLoading: boolean
  onRefresh: () => void
  isRefreshing: boolean
}) {
  const tableRef = useRef<HTMLDivElement>(null)
  const {
    searchQuery,
    setSearchQuery,
    sortField,
    sortDirection,
    expandedIndex,
    focusedRowIndex,
    clientFilter,
    setClientFilter,
    refreshInterval,
    setRefreshInterval,
    uniqueClients,
    sortedRequests,
    handleSort,
    handleToggleExpand,
    handleKeyDown,
    handleExport,
  } = useBlockedRequestsTable(requests, onRefresh)

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/30 overflow-hidden">
      {/* Table Controls */}
      <TableControls
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        clientFilter={clientFilter}
        onClientFilterChange={setClientFilter}
        uniqueClients={uniqueClients}
        refreshInterval={refreshInterval}
        onRefreshIntervalChange={setRefreshInterval}
        onExport={handleExport}
        isRefreshing={isRefreshing}
        sortedCount={sortedRequests.length}
        totalCount={requests.length}
        hasExportData={sortedRequests.length > 0}
      />

      {/* Table */}
      <div
        ref={tableRef}
        onKeyDown={handleKeyDown}
        className="max-h-[600px] overflow-auto focus:outline-none"
      >
        {/* Table Header */}
        <div className="sticky top-0 z-10 bg-slate-900/95 backdrop-blur-sm border-b border-slate-800">
          <div
            className={`grid ${TABLE_GRID_COLS} gap-3 px-4 py-3 items-center`}
          >
            <SortableHeader
              label="Time"
              field="timestamp"
              currentField={sortField}
              direction={sortDirection}
              onSort={handleSort}
            />
            <SortableHeader
              label="Client"
              field="client_name"
              currentField={sortField}
              direction={sortDirection}
              onSort={handleSort}
            />
            <SortableHeader
              label="Endpoint"
              field="endpoint"
              currentField={sortField}
              direction={sortDirection}
              onSort={handleSort}
            />
            <SortableHeader
              label="Reason"
              field="block_reason"
              currentField={sortField}
              direction={sortDirection}
              onSort={handleSort}
            />
            <div />
          </div>
        </div>

        {/* Loading State */}
        {isLoading && (
          <div className="divide-y divide-slate-800/50">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className={`grid ${TABLE_GRID_COLS} gap-3 px-4 py-3 items-center`}
              >
                <div className="h-4 w-16 rounded animate-shimmer" />
                <div className="h-4 w-24 rounded animate-shimmer" />
                <div className="h-4 w-full max-w-xs rounded animate-shimmer" />
                <div className="h-4 w-32 rounded animate-shimmer" />
                <div className="h-4 w-4 rounded animate-shimmer" />
              </div>
            ))}
          </div>
        )}

        {/* Empty State */}
        {!isLoading && sortedRequests.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="p-4 rounded-full bg-emerald-900/30 mb-4">
              <Shield className="w-10 h-10 text-emerald-400" />
            </div>
            <h3 className="text-lg font-semibold text-slate-100 mb-1">
              {requests.length === 0
                ? 'No blocked requests'
                : 'No matching requests'}
            </h3>
            <p className="text-sm text-slate-500 max-w-sm">
              {requests.length === 0
                ? 'All systems operational. Blocked requests will appear here when access is denied.'
                : 'Try adjusting your search or filter criteria'}
            </p>
          </div>
        )}

        {/* Table Rows */}
        {!isLoading && sortedRequests.length > 0 && (
          <div className="divide-y divide-slate-800/50">
            {sortedRequests.map((request, index) => (
              <BlockedRequestRow
                key={index}
                request={request}
                index={index}
                isFocused={focusedRowIndex === index}
                isExpanded={expandedIndex === index}
                onToggleExpand={handleToggleExpand}
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer Stats */}
      {!isLoading && requests.length > 0 && (
        <div className="px-4 py-2 border-t border-slate-800 flex items-center justify-between text-xs text-slate-500">
          <span>
            {sortedRequests.length} of {requests.length} requests
          </span>
          <div className="flex items-center gap-1">
            <span className="px-1.5 py-0.5 rounded bg-slate-800 font-mono">
              j/k
            </span>
            <span>navigate</span>
            <span className="px-1.5 py-0.5 rounded bg-slate-800 font-mono ml-2">
              Enter
            </span>
            <span>expand</span>
          </div>
        </div>
      )}
    </div>
  )
}
