'use client'

import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import {
  Activity,
  CheckCircle2,
  Clock,
  RefreshCw,
  Terminal,
  Zap,
} from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { fetchMonitoringMetrics, fetchRequestLog } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Filters } from './components/Filters'
import { MetricCard } from './components/MetricCard'
import { RequestTable } from './components/RequestTable'
import { ToolTypeDistribution } from './components/ToolTypeDistribution'
import { TopEndpoints } from './components/TopEndpoints'
import { TopTools } from './components/TopTools'
import type { SortDirection, SortField } from './types'
import { formatLatency, formatNumber } from './utils'

export default function MonitoringRequestsPage() {
  // Filters
  const [clientFilter, setClientFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState<number | undefined>()
  const [toolTypeFilter, setToolTypeFilter] = useState<string | undefined>()
  const [agentFilter, setAgentFilter] = useState('')
  const [rejectedOnly, setRejectedOnly] = useState(false)
  const [timeRange, setTimeRange] = useState(24)
  const [sortField, setSortField] = useState<SortField>('time')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const pageSize = 50

  // Sort handler
  const handleSort = useCallback(
    (field: SortField) => {
      if (sortField === field) {
        setSortDirection((d) => (d === 'desc' ? 'asc' : 'desc'))
      } else {
        setSortField(field)
        setSortDirection('desc')
      }
    },
    [sortField],
  )

  // Queries
  const { data: metrics, isLoading: metricsLoading } = useQuery({
    queryKey: ['monitoring-metrics', timeRange],
    queryFn: () => fetchMonitoringMetrics(timeRange),
    refetchInterval: 30000,
  })

  const {
    data,
    isLoading,
    error,
    refetch,
    isFetching,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: [
      'request-log',
      clientFilter,
      statusFilter,
      toolTypeFilter,
      agentFilter,
      rejectedOnly,
    ],
    queryFn: ({ pageParam = 0 }) =>
      fetchRequestLog({
        client_id: clientFilter || undefined,
        status_code: statusFilter,
        tool_type: toolTypeFilter,
        agent_slug: agentFilter || undefined,
        rejected_only: rejectedOnly,
        limit: pageSize,
        offset: pageParam * pageSize,
      }),
    getNextPageParam: (lastPage, allPages) => {
      const totalLoaded = allPages.length * pageSize
      return totalLoaded < lastPage.total ? allPages.length : undefined
    },
    initialPageParam: 0,
    refetchInterval: 10000,
  })

  // Flatten and sort requests
  const requests = useMemo(() => {
    const flat = data?.pages.flatMap((page) => page.requests) ?? []

    return [...flat].sort((a, b) => {
      let cmp = 0
      switch (sortField) {
        case 'time':
          cmp =
            new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
          break
        case 'type':
          cmp = (a.tool_type || '').localeCompare(b.tool_type || '')
          break
        case 'tool':
          cmp = (a.tool_name || '').localeCompare(b.tool_name || '')
          break
        case 'agent':
          cmp = (a.agent_slug || '').localeCompare(b.agent_slug || '')
          break
        case 'status':
          cmp = a.status_code - b.status_code
          break
        case 'latency':
          cmp = (a.latency_ms || 0) - (b.latency_ms || 0)
          break
      }
      return sortDirection === 'asc' ? cmp : -cmp
    })
  }, [data, sortField, sortDirection])
  const total = data?.pages[0]?.total ?? 0

  // Derived metrics
  const successStatus = useMemo(() => {
    if (!metrics?.summary) return 'neutral' as const
    const rate = metrics.summary.success_rate
    if (rate >= 95) return 'success' as const
    if (rate >= 80) return 'warning' as const
    return 'error' as const
  }, [metrics])

  const latencyStatus = useMemo(() => {
    if (!metrics?.summary) return 'neutral' as const
    const ms = metrics.summary.avg_latency_ms
    if (ms < 500) return 'success' as const
    if (ms < 2000) return 'warning' as const
    return 'error' as const
  }, [metrics])

  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />

      <header className="page-header">
        <div className="page-container px-4 lg:px-8">
          <div className="page-header-row">
            <div className="page-title-group">
              <div className="page-title-icon">
                <Activity className="h-5 w-5" />
              </div>
              <div className="page-title-stack">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="page-title">Request Monitoring</h1>
                  {total > 0 && (
                    <span className="page-pill">
                      {formatNumber(total)} total
                    </span>
                  )}
                </div>
                <div className="page-meta">
                  <span>
                    Inspect request traffic, tool mix, response quality, and
                    live endpoint pressure.
                  </span>
                </div>
              </div>
            </div>
            <div className="page-toolbar">
              <div className="rounded-2xl border border-slate-800/80 bg-slate-900/80 p-1 shadow-[0_18px_40px_-30px_rgba(0,0,0,0.9)]">
                <div className="flex items-center gap-1">
                  {[
                    { value: 1, label: '1h' },
                    { value: 6, label: '6h' },
                    { value: 24, label: '24h' },
                    { value: 72, label: '3d' },
                    { value: 168, label: '7d' },
                  ].map(({ value, label }) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setTimeRange(value)}
                      className={cn(
                        'rounded-xl px-3 py-1.5 text-xs font-semibold transition-all duration-150',
                        timeRange === value
                          ? 'bg-amber-500 text-slate-950 shadow-[0_16px_28px_-22px_rgba(245,158,11,0.9)]'
                          : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100',
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <button
                onClick={() => refetch()}
                disabled={isFetching}
                className="button-secondary"
              >
                <RefreshCw
                  className={cn('h-4 w-4', isFetching && 'animate-spin')}
                />
                Refresh
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="page-frame">
        <div className="page-container space-y-6">
          {/* Metrics Summary Row */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              label="Total Requests"
              value={
                metricsLoading
                  ? '...'
                  : formatNumber(metrics?.summary.total_requests || 0)
              }
              subtext={`Last ${timeRange}h`}
              icon={Activity}
              status="neutral"
            />
            <MetricCard
              label="Success Rate"
              value={
                metricsLoading
                  ? '...'
                  : `${(metrics?.summary.success_rate || 0).toFixed(1)}%`
              }
              subtext="2xx/3xx responses"
              icon={CheckCircle2}
              status={successStatus}
            />
            <MetricCard
              label="Avg Latency"
              value={
                metricsLoading
                  ? '...'
                  : formatLatency(metrics?.summary.avg_latency_ms ?? 0)
              }
              subtext="P50 response time"
              icon={Zap}
              status={latencyStatus}
            />
            <MetricCard
              label="Tool Types"
              value={
                metricsLoading
                  ? '...'
                  : String(metrics?.by_tool_type.length || 0)
              }
              subtext="API, CLI, SDK"
              icon={Terminal}
              status="neutral"
            />
          </div>

          {/* Distribution & Top Sections */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Tool Type Distribution */}
            <div className="panel-surface p-5">
              <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-4">
                Request Distribution by Tool Type
              </h2>
              {metricsLoading ? (
                <div className="h-16 rounded-xl animate-shimmer" />
              ) : (
                <ToolTypeDistribution data={metrics?.by_tool_type || []} />
              )}
            </div>

            {/* Top Tools */}
            <div className="panel-surface p-5">
              <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-4">
                Top Tools (CLI/SDK)
              </h2>
              {metricsLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-12 rounded-xl animate-shimmer" />
                  ))}
                </div>
              ) : (
                <TopTools data={metrics?.by_tool_name || []} />
              )}
            </div>

            {/* Top Endpoints */}
            <div className="panel-surface p-5">
              <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-4">
                Top Endpoints
              </h2>
              {metricsLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-12 rounded-xl animate-shimmer" />
                  ))}
                </div>
              ) : (
                <TopEndpoints data={metrics?.by_endpoint || []} />
              )}
            </div>
          </div>

          {/* Filters */}
          <Filters
            clientFilter={clientFilter}
            setClientFilter={setClientFilter}
            agentFilter={agentFilter}
            setAgentFilter={setAgentFilter}
            toolTypeFilter={toolTypeFilter}
            setToolTypeFilter={setToolTypeFilter}
            statusFilter={statusFilter}
            setStatusFilter={setStatusFilter}
            rejectedOnly={rejectedOnly}
            setRejectedOnly={setRejectedOnly}
          />

          {/* Error State */}
          {error && (
            <div className="rounded-2xl border border-red-800/50 bg-red-900/20 p-4">
              <p className="text-sm text-red-400">Failed to load request log</p>
            </div>
          )}

          {/* Table */}
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3, 4, 5].map((i) => (
                <div
                  key={i}
                  className="h-14 rounded-2xl bg-slate-800 animate-pulse"
                />
              ))}
            </div>
          ) : requests.length === 0 ? (
            <div className="empty-surface flex flex-col items-center justify-center">
              <Clock className="h-10 w-10 mb-3 text-slate-600" />
              <p className="text-sm font-medium text-slate-300">
                No requests found
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Try adjusting your filters or time range
              </p>
            </div>
          ) : (
            <RequestTable
              requests={requests}
              total={total}
              sortField={sortField}
              sortDirection={sortDirection}
              onSort={handleSort}
              isFetchingNextPage={isFetchingNextPage}
              hasNextPage={hasNextPage}
              onFetchNextPage={fetchNextPage}
            />
          )}
        </div>
      </main>
    </div>
  )
}
