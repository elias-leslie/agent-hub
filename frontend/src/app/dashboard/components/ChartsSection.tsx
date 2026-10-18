import { ProviderStatusCard } from '@/components/dashboard/ProviderStatusCard'
import { Sparkline } from '@/components/dashboard/Sparkline'
import type { StatusResponse } from '@/lib/api/status'
import { formatNumber } from '@/lib/formatters'

interface ChartsSectionProps {
  /** Model calls per day; the same population as the Model calls KPI. */
  requestsByDay: number[]
  /** Model calls in the period, or undefined while stats load. */
  requestTotal: number | undefined
  requestsLoading: boolean
  statusLoading: boolean
  status: StatusResponse | undefined
}

export function ChartsSection({
  requestsByDay,
  requestTotal,
  requestsLoading,
  statusLoading,
  status,
}: ChartsSectionProps) {
  return (
    <>
      {/* Request Volume Chart */}
      <div className="panel-surface col-span-12 overflow-hidden p-5 xl:col-span-7 xl:p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              Request Volume
            </h2>
            <p className="mt-1 text-sm text-slate-300">
              Model calls per day (POST /api/complete).
            </p>
          </div>
          <div className="flex items-center gap-4 text-[10px] font-mono text-slate-500">
            <span className="flex items-center gap-1.5 rounded-full border border-slate-800/70 bg-slate-900/80 px-2.5 py-1">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              {requestTotal == null ? '-' : formatNumber(requestTotal)} calls
            </span>
          </div>
        </div>
        <div className="h-40 rounded-2xl border border-slate-800/70 bg-slate-950/55 p-3">
          {requestsLoading ? (
            <div className="h-full rounded-xl animate-shimmer" />
          ) : (
            <Sparkline data={requestsByDay} color="emerald" showDot />
          )}
        </div>
      </div>

      {/* Provider Health Panel */}
      <div className="panel-surface col-span-12 overflow-hidden p-5 xl:col-span-5 xl:p-6">
        <div className="mb-4">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            Provider Health
          </h2>
          <p className="mt-1 text-sm text-slate-300">
            Whether each provider can take requests on this host.
          </p>
        </div>
        <div className="space-y-2.5">
          {statusLoading ? (
            <>
              <div className="h-18 rounded-2xl animate-shimmer" />
              <div className="h-18 rounded-2xl animate-shimmer" />
            </>
          ) : status?.providers?.length ? (
            status.providers.map((provider) => (
              <ProviderStatusCard key={provider.name} provider={provider} />
            ))
          ) : (
            <p className="text-sm text-slate-400">No providers configured</p>
          )}
        </div>
      </div>
    </>
  )
}
