import { Activity, AlertTriangle, Clock, DollarSign, Sigma } from 'lucide-react'

import { ChartCard } from '@/app/agents/[slug]/analytics/components/ChartCard'
import { ChartSection } from '@/app/agents/[slug]/analytics/components/ChartSection'
import { KPICard } from '@/app/agents/[slug]/analytics/components/KPICard'
import type { AnalyticsData } from '@/app/agents/[slug]/analytics/types'
import { formatLatency } from '@/lib/formatters'

interface RuntimePanelsProps {
  analytics: AnalyticsData | null
  primaryModel: string | null
  hasRuntimeActivity: boolean
  runtimeErrorMessage: string | null
}

export function RuntimePanels({
  analytics,
  primaryModel,
  hasRuntimeActivity,
  runtimeErrorMessage,
}: RuntimePanelsProps) {
  if (runtimeErrorMessage || !analytics) {
    return (
      <div className="mt-6">
        <ChartCard title="Runtime view">
          <div className="rounded-2xl border border-dashed border-amber-900 bg-amber-950/20 px-6 py-10 text-center">
            <p className="text-sm font-semibold text-slate-100">
              Runtime metrics unavailable
            </p>
            <p className="mt-2 text-sm text-slate-400">
              {runtimeErrorMessage ??
                'No runtime metrics are available for this agent yet.'}
            </p>
          </div>
        </ChartCard>
      </div>
    )
  }

  return (
    <>
      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KPICard
          label="24h Cost"
          value={`$${analytics.totalCostUsd.toFixed(2)}`}
          icon={DollarSign}
          color="blue"
        />
        <KPICard
          label="Avg Latency"
          value={formatLatency(analytics.avgLatencyMs)}
          icon={Clock}
          color="amber"
        />
        <KPICard
          label="Error Rate"
          value={`${analytics.errorRate}%`}
          icon={AlertTriangle}
          color="red"
        />
        <KPICard
          label="Success Rate"
          value={`${analytics.successRate}%`}
          icon={Activity}
          color="green"
        />
      </div>

      <div className="mt-6">
        {hasRuntimeActivity ? (
          <ChartSection trend={analytics.trend} />
        ) : (
          <ChartCard title="Activity window">
            <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/40 px-6 py-10 text-center">
              <p className="text-sm font-medium text-slate-100">
                No recent runtime activity
              </p>
              <p className="mt-2 text-sm text-slate-400">
                This agent has not handled any requests in the last 24 hours
                yet.
              </p>
            </div>
          </ChartCard>
        )}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <ChartCard title="24h Throughput">
          <div className="space-y-4">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-400">Requests</span>
              <span className="font-semibold text-slate-100">
                {analytics.totalRequests}
              </span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-400">Requests / hour</span>
              <span className="font-semibold text-slate-100">
                {analytics.requestsPerHour}
              </span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-400">Tokens</span>
              <span className="font-semibold text-slate-100">
                {analytics.totalTokens.toLocaleString()}
              </span>
            </div>
          </div>
        </ChartCard>

        <ChartCard title="Model routing">
          <div className="space-y-2">
            {analytics.modelSummary.map((model) => (
              <div
                key={model}
                className="flex items-center justify-between rounded-lg border border-slate-700 px-3 py-2 text-sm"
              >
                <span className="break-all text-slate-300">{model}</span>
                <Sigma className="h-4 w-4 text-slate-400" />
              </div>
            ))}
          </div>
        </ChartCard>

        <ChartCard title="Freshness">
          <div className="space-y-4 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Metrics basis</span>
              <span className="font-semibold text-slate-100">
                24h aggregate
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Agent updated</span>
              <span className="font-semibold text-slate-100">
                {new Date(analytics.lastUpdatedAt).toLocaleString()}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Primary model</span>
              <span className="font-semibold text-slate-100">
                {primaryModel ?? 'Unassigned'}
              </span>
            </div>
          </div>
        </ChartCard>
      </div>
    </>
  )
}
