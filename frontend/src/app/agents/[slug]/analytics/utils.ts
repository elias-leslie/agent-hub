import type {
  Agent,
  AgentBenchmarkTrendPoint,
  AgentMetrics,
  AnalyticsData,
} from './types'

export function metricsToAnalytics(
  metrics: AgentMetrics,
  agent: Agent,
): AnalyticsData {
  const trend = metrics.latency_trend.map((latencyMs, index) => ({
    hour: `${String(index).padStart(2, '0')}:00`,
    latencyMs,
    successRate: Number((metrics.success_trend[index] ?? 0).toFixed(1)),
  }))

  return {
    totalCostUsd: metrics.cost_24h_usd,
    avgLatencyMs: metrics.avg_latency_ms,
    errorRate: Number((100 - metrics.success_rate).toFixed(1)),
    successRate: Number(metrics.success_rate.toFixed(1)),
    totalRequests: metrics.requests_24h,
    totalTokens: metrics.tokens_24h,
    requestsPerHour: Number((metrics.requests_24h / 24).toFixed(1)),
    trend,
    modelSummary: [agent.primary_model_id, ...agent.fallback_models],
    lastUpdatedAt: agent.updated_at,
  }
}

export function sliceTrendWindow(trend: AnalyticsData['trend'], hours: number) {
  return trend.slice(Math.max(0, trend.length - hours))
}

export function filterBenchmarkTrendWindow(
  trend: AgentBenchmarkTrendPoint[],
  hours: number,
) {
  const cutoff = Date.now() - hours * 60 * 60 * 1000
  const filtered = trend.filter((point) => {
    if (!point.completed_at) {
      return false
    }
    return new Date(point.completed_at).getTime() >= cutoff
  })
  return filtered.length > 0
    ? filtered
    : trend.slice(Math.max(0, trend.length - 8))
}
