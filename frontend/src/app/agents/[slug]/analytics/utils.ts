import type { Agent, AgentMetrics, AnalyticsData } from "./types";

export function metricsToAnalytics(
  metrics: AgentMetrics,
  agent: Agent
): AnalyticsData {
  const baseRequests = metrics.requests_24h || 1;
  return {
    total_cost_usd: metrics.cost_24h_usd,
    avg_latency_ms: metrics.avg_latency_ms,
    error_rate: 100 - metrics.success_rate,
    cache_hit_rate: 0,
    total_requests: metrics.requests_24h,
    model_distribution: [
      {
        model: agent.primary_model_id,
        count: Math.floor(baseRequests * 0.7),
        percentage: 70,
      },
      ...agent.fallback_models.slice(0, 2).map((m, i) => ({
        model: m,
        count: Math.floor(baseRequests * (0.2 - i * 0.05)),
        percentage: 20 - i * 5,
      })),
    ],
    latency_histogram: [
      { range: "0-200ms", count: Math.floor(baseRequests * 0.1) },
      { range: "200-500ms", count: Math.floor(baseRequests * 0.15) },
      { range: "500-1s", count: Math.floor(baseRequests * 0.35) },
      { range: "1-2s", count: Math.floor(baseRequests * 0.25) },
      { range: "2-5s", count: Math.floor(baseRequests * 0.12) },
      { range: "5s+", count: Math.floor(baseRequests * 0.03) },
    ],
    recent_failures: [],
    trend: {
      cost_change: 0,
      latency_change: 0,
      error_change: 0,
    },
  };
}
