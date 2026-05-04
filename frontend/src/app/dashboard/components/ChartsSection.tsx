import { ProviderStatusCard } from '@/components/dashboard/ProviderStatusCard'
import { Sparkline } from '@/components/dashboard/Sparkline'
import type { StatusResponse } from '@/lib/api/status'
import { formatCurrency, formatNumber } from '@/lib/formatters'

interface ChartsSectionProps {
  requestsByDay: number[]
  costByDay: number[]
  totalCosts:
    | {
        total_requests: number
        total_cost_usd: number
      }
    | undefined
  dailyLoading: boolean
  statusLoading: boolean
  status: StatusResponse | undefined
  costsByModel:
    | {
        aggregations: Array<{
          input_tokens: number
          output_tokens: number
        }>
      }
    | undefined
}

export function ChartsSection({
  requestsByDay,
  costByDay,
  totalCosts,
  dailyLoading,
  statusLoading,
  status,
  costsByModel,
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
              Demand and spend over the active time window.
            </p>
          </div>
          <div className="flex items-center gap-4 text-[10px] font-mono text-slate-500">
            <span className="flex items-center gap-1.5 rounded-full border border-slate-800/70 bg-slate-900/80 px-2.5 py-1">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              {formatNumber(totalCosts?.total_requests || 0)} total
            </span>
          </div>
        </div>
        <div className="h-40 rounded-2xl border border-slate-800/70 bg-slate-950/55 p-3">
          {dailyLoading ? (
            <div className="h-full rounded-xl animate-shimmer" />
          ) : (
            <Sparkline data={requestsByDay} color="emerald" showDot />
          )}
        </div>
        <div className="mt-4 grid gap-3 border-t border-slate-800/60 pt-4 md:grid-cols-[1.4fr_0.8fr]">
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                Daily Spend
              </span>
              <span className="text-[10px] font-mono text-amber-300">
                {formatCurrency(totalCosts?.total_cost_usd || 0)} total
              </span>
            </div>
            <div className="h-20 rounded-2xl border border-slate-800/70 bg-slate-950/55 p-3">
              <Sparkline data={costByDay} color="amber" showDot />
            </div>
          </div>
          <div className="rounded-2xl border border-slate-800/70 bg-slate-950/55 p-4">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              Token Flow
            </p>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <div>
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Input
                </p>
                <p className="text-xl font-mono font-semibold text-slate-100">
                  {formatNumber(
                    costsByModel?.aggregations.reduce(
                      (sum, a) => sum + a.input_tokens,
                      0,
                    ) || 0,
                  )}
                </p>
              </div>
              <div>
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Output
                </p>
                <p className="text-xl font-mono font-semibold text-slate-100">
                  {formatNumber(
                    costsByModel?.aggregations.reduce(
                      (sum, a) => sum + a.output_tokens,
                      0,
                    ) || 0,
                  )}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Provider Health Panel */}
      <div className="panel-surface col-span-12 overflow-hidden p-5 xl:col-span-5 xl:p-6">
        <div className="mb-4">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            Provider Health
          </h2>
          <p className="mt-1 text-sm text-slate-300">
            Availability and latency across configured providers.
          </p>
        </div>
        <div className="space-y-2.5">
          {statusLoading ? (
            <>
              <div className="h-18 rounded-2xl animate-shimmer" />
              <div className="h-18 rounded-2xl animate-shimmer" />
            </>
          ) : status?.providers ? (
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
