import {
  Activity,
  ArrowRightLeft,
  Clock,
  DollarSign,
  Layers,
  MessageSquare,
  Zap,
} from 'lucide-react'
import { KPICard } from '@/components/dashboard/KPICard'
import { formatCurrency, formatLatency, formatNumber } from '@/lib/formatters'

interface KPISectionProps {
  dashboardStats:
    | {
        requests: {
          total_requests: number
          success_rate: number
          p50_latency_ms?: number
          p95_latency_ms?: number
          error_count: number
          timeout_count?: number
          fallback_count?: number
          fallback_success_rate?: number
        }
        active_sessions?: number
        total_sessions?: number
        total_cost_usd?: number
        total_tokens?: number
        memory: {
          total_injections: number
          total_mandates: number
        }
      }
    | undefined
  activeSessionCount: number
  totalCosts:
    | {
        total_cost_usd: number
        total_tokens: number
      }
    | undefined
}

export function KPISection({
  dashboardStats,
  activeSessionCount,
  totalCosts,
}: KPISectionProps) {
  const timeoutCount = dashboardStats?.requests.timeout_count || 0
  const totalReqs = dashboardStats?.requests.total_requests || 0
  const timeoutRate = totalReqs > 0 ? (timeoutCount / totalReqs) * 100 : 0
  const fallbackCount = dashboardStats?.requests.fallback_count || 0
  const fallbackSuccessRate =
    dashboardStats?.requests.fallback_success_rate ?? 100

  return (
    <div className="col-span-12 grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-4 mb-2">
      <KPICard
        label="Requests"
        value={formatNumber(totalReqs)}
        subtext={`${dashboardStats?.requests.success_rate.toFixed(1)}% success`}
        icon={Activity}
        status={
          dashboardStats?.requests.success_rate &&
          dashboardStats.requests.success_rate < 90
            ? 'warning'
            : 'success'
        }
      />
      <KPICard
        label="Latency"
        value={
          dashboardStats?.requests.p50_latency_ms
            ? formatLatency(dashboardStats.requests.p50_latency_ms)
            : 'N/A'
        }
        subtext={
          dashboardStats?.requests.p95_latency_ms
            ? `P95: ${formatLatency(dashboardStats.requests.p95_latency_ms)}`
            : 'No latency data'
        }
        icon={Zap}
        status={
          dashboardStats?.requests.p50_latency_ms &&
          dashboardStats.requests.p50_latency_ms > 1000
            ? 'warning'
            : 'success'
        }
      />
      <KPICard
        label="Success"
        value={
          dashboardStats?.requests.success_rate
            ? `${dashboardStats.requests.success_rate.toFixed(1)}%`
            : '100%'
        }
        subtext={`${dashboardStats?.requests.error_count || 0} failed requests`}
        icon={Activity}
        status={
          dashboardStats?.requests.success_rate &&
          dashboardStats.requests.success_rate < 95
            ? dashboardStats.requests.success_rate < 85
              ? 'error'
              : 'warning'
            : 'success'
        }
      />
      <KPICard
        label="Sessions"
        value={formatNumber(
          dashboardStats?.active_sessions || activeSessionCount,
        )}
        subtext={`${dashboardStats?.total_sessions || 0} total sessions`}
        icon={MessageSquare}
        status="success"
        pulse={activeSessionCount > 0}
      />
      <KPICard
        label="Cost"
        value={formatCurrency(
          dashboardStats?.total_cost_usd || totalCosts?.total_cost_usd || 0,
        )}
        subtext={
          dashboardStats?.total_tokens
            ? `${formatNumber(dashboardStats.total_tokens)} tokens`
            : `${formatNumber(totalCosts?.total_tokens || 0)} tokens`
        }
        icon={DollarSign}
        status="neutral"
      />
      <KPICard
        label="Memory"
        value={formatNumber(dashboardStats?.memory.total_injections || 0)}
        subtext={`${formatNumber(dashboardStats?.memory.total_mandates || 0)} mandates`}
        icon={Layers}
        status="success"
      />
      <KPICard
        label="Timeouts"
        value={`${timeoutRate.toFixed(1)}%`}
        subtext={`${timeoutCount} timed out`}
        icon={Clock}
        status={
          timeoutRate > 5 ? 'error' : timeoutRate > 2 ? 'warning' : 'success'
        }
      />
      <KPICard
        label="Fallbacks"
        value={formatNumber(fallbackCount)}
        subtext={`${fallbackSuccessRate.toFixed(0)}% success`}
        icon={ArrowRightLeft}
        status={
          fallbackCount > 0 && fallbackSuccessRate < 50 ? 'warning' : 'success'
        }
      />
    </div>
  )
}
