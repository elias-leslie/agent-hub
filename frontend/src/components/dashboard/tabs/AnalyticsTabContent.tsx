import { Activity } from 'lucide-react'
import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { DashboardStatsResponse } from '@/lib/api/dashboard'
import { formatLatency, formatModelName, formatNumber } from '@/lib/formatters'
import { LatencyDistributionChart } from './LatencyDistributionChart'

// Request latency and model mix for /api/complete. Spend lives on the Costs page.
export function AnalyticsTabContent({
  isLoading,
  dashboardStats,
}: {
  isLoading: boolean
  dashboardStats?: DashboardStatsResponse
}) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4 h-48">
        <div className="bg-slate-800 rounded animate-pulse" />
        <div className="bg-slate-800 rounded animate-pulse" />
      </div>
    )
  }

  const modelBreakdown =
    dashboardStats?.by_model?.slice(0, 10).map((m) => ({
      model: formatModelName(m.model),
      requests: m.request_count,
      latency: m.avg_latency_ms,
    })) || []

  return (
    <div className="space-y-4">
      <LatencyDistributionChart />

      {/* Model Usage Breakdown */}
      {modelBreakdown.length > 0 && (
        <div className="p-4 rounded-lg bg-slate-800/40 border border-slate-700/50">
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
            <Activity className="h-3 w-3 text-emerald-500" />
            Model Usage (Top 10)
          </h4>
          <ResponsiveContainer
            width="100%"
            height={Math.max(160, modelBreakdown.length * 28)}
          >
            <BarChart
              data={modelBreakdown}
              layout="vertical"
              barCategoryGap="20%"
            >
              <XAxis
                type="number"
                tick={{ fontSize: 10, fill: '#64748b' }}
                hide
              />
              <YAxis
                type="category"
                dataKey="model"
                tick={{ fontSize: 9, fill: '#94a3b8' }}
                width={90}
              />
              <Tooltip
                formatter={(value: unknown, name?: string | number) =>
                  name === 'requests'
                    ? formatNumber(Number(value))
                    : formatLatency(Number(value))
                }
                contentStyle={{
                  background: '#0f172a',
                  border: '1px solid #1e293b',
                  borderRadius: '8px',
                  fontSize: '12px',
                  color: '#f1f5f9',
                  boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1)',
                }}
              />
              <Bar dataKey="requests" fill="#10b981" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
