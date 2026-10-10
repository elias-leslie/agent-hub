import {
  Activity,
  DollarSign,
  Layers,
  MessageSquare,
  ShieldCheck,
  Zap,
} from 'lucide-react'
import { KPICard } from '@/components/dashboard/KPICard'
import type { DashboardStatsResponse } from '@/lib/api/dashboard'
import { formatCurrency, formatLatency, formatNumber } from '@/lib/formatters'

interface KPISectionProps {
  dashboardStats: DashboardStatsResponse | undefined
  activeSessionCount: number
  totalCosts:
    | {
        total_cost_usd: number
        total_tokens: number
      }
    | undefined
}

type KPIStatus = 'success' | 'warning' | 'error' | 'neutral'

function successStatus(rate: number | null | undefined): KPIStatus {
  if (rate == null) return 'neutral'
  if (rate < 85) return 'error'
  if (rate < 95) return 'warning'
  return 'success'
}

// Request, latency and success figures cover model calls (POST /api/complete)
// only; dashboard and other HTTP traffic is excluded by the backend.
export function KPISection({
  dashboardStats,
  activeSessionCount,
  totalCosts,
}: KPISectionProps) {
  const requests = dashboardStats?.requests
  const totalCalls = requests?.total_requests ?? 0
  const successRate = requests?.success_rate
  const p50 = requests?.p50_latency_ms
  const p95 = requests?.p95_latency_ms
  const cost = dashboardStats?.total_cost_usd ?? totalCosts?.total_cost_usd ?? 0
  const tokens = dashboardStats?.total_tokens ?? totalCosts?.total_tokens ?? 0
  const memory = dashboardStats?.memory

  return (
    <div className="col-span-12 grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4 mb-2">
      <KPICard
        label="Model calls"
        value={formatNumber(totalCalls)}
        subtext={
          !dashboardStats
            ? 'No request data'
            : successRate != null
              ? `${successRate.toFixed(1)}% succeeded`
              : 'No model calls in this period'
        }
        icon={Activity}
        status={successStatus(successRate)}
      />
      <KPICard
        label="Latency"
        value={p50 != null ? formatLatency(p50) : 'N/A'}
        subtext={p95 != null ? `P95: ${formatLatency(p95)}` : 'No latency data'}
        icon={Zap}
        status={p50 == null ? 'neutral' : p50 > 1000 ? 'warning' : 'success'}
      />
      <KPICard
        label="Success"
        value={successRate != null ? `${successRate.toFixed(1)}%` : 'N/A'}
        subtext={`${formatNumber(requests?.error_count ?? 0)} failed calls`}
        icon={ShieldCheck}
        status={successStatus(successRate)}
      />
      <KPICard
        label="Sessions"
        value={formatNumber(
          dashboardStats?.active_sessions ?? activeSessionCount,
        )}
        subtext={`${formatNumber(dashboardStats?.total_sessions ?? 0)} total sessions`}
        icon={MessageSquare}
        status="success"
        pulse={activeSessionCount > 0}
      />
      <KPICard
        label="Metered spend"
        value={formatCurrency(cost)}
        subtext={`API-billed calls, ${formatNumber(tokens)} tokens`}
        icon={DollarSign}
        status="neutral"
      />
      <KPICard
        label="Memory"
        value={formatNumber(memory?.total_injections ?? 0)}
        subtext={`${formatNumber(memory?.total_references ?? 0)} selected, ${formatNumber(memory?.total_reference_index_entries ?? 0)} passive refs`}
        icon={Layers}
        status="success"
      />
    </div>
  )
}
