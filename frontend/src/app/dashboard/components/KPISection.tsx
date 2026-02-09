import {
  Activity,
  DollarSign,
  Zap,
  MessageSquare,
  Layers,
} from "lucide-react";
import { KPICard } from "@/components/dashboard/KPICard";
import { formatCurrency, formatNumber, formatLatency } from "@/lib/formatters";

interface KPISectionProps {
  dashboardStats: {
    requests: {
      total_requests: number;
      success_rate: number;
      p50_latency_ms?: number;
      p95_latency_ms?: number;
      error_count: number;
    };
    active_sessions?: number;
    total_sessions?: number;
    total_cost_usd?: number;
    total_tokens?: number;
    memory: {
      total_injections: number;
      total_mandates: number;
    };
  } | undefined;
  activeSessionCount: number;
  totalCosts: {
    total_cost_usd: number;
    total_tokens: number;
  } | undefined;
}

export function KPISection({
  dashboardStats,
  activeSessionCount,
  totalCosts,
}: KPISectionProps) {
  return (
    <div className="col-span-12 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 mb-2">
      <KPICard
        label="Total Requests"
        value={formatNumber(dashboardStats?.requests.total_requests || 0)}
        subtext={`${dashboardStats?.requests.success_rate.toFixed(1)}% success`}
        icon={Activity}
        status={dashboardStats?.requests.success_rate && dashboardStats.requests.success_rate < 90 ? "warning" : "success"}
      />
      <KPICard
        label="Avg Latency"
        value={dashboardStats?.requests.p50_latency_ms ? formatLatency(dashboardStats.requests.p50_latency_ms) : "N/A"}
        subtext={dashboardStats?.requests.p95_latency_ms ? `P95: ${formatLatency(dashboardStats.requests.p95_latency_ms)}` : "No latency data"}
        icon={Zap}
        status={dashboardStats?.requests.p50_latency_ms && dashboardStats.requests.p50_latency_ms > 1000 ? "warning" : "success"}
      />
      <KPICard
        label="Success Rate"
        value={dashboardStats?.requests.success_rate ? `${dashboardStats.requests.success_rate.toFixed(1)}%` : "100%"}
        subtext={`${dashboardStats?.requests.error_count || 0} failed requests`}
        icon={Activity}
        status={dashboardStats?.requests.success_rate && dashboardStats.requests.success_rate < 95 ? (dashboardStats.requests.success_rate < 85 ? "error" : "warning") : "success"}
      />
      <KPICard
        label="Active Sessions"
        value={formatNumber(dashboardStats?.active_sessions || activeSessionCount)}
        subtext={`${dashboardStats?.total_sessions || 0} total sessions`}
        icon={MessageSquare}
        status="success"
        pulse={activeSessionCount > 0}
      />
      <KPICard
        label="Total Cost"
        value={formatCurrency(dashboardStats?.total_cost_usd || totalCosts?.total_cost_usd || 0)}
        subtext={dashboardStats?.total_tokens ? `${formatNumber(dashboardStats.total_tokens)} tokens` : `${formatNumber(totalCosts?.total_tokens || 0)} tokens`}
        icon={DollarSign}
        status="neutral"
      />
      <KPICard
        label="Memory Injection"
        value={formatNumber(dashboardStats?.memory.total_injections || 0)}
        subtext={`${formatNumber(dashboardStats?.memory.total_mandates || 0)} mandates`}
        icon={Layers}
        status="success"
      />
    </div>
  );
}
