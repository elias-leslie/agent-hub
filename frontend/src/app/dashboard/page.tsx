"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  DollarSign,
  Zap,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  TrendingUp,
  Server,
  Cpu,
  ThumbsUp,
  ThumbsDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchStatus,
  fetchCosts,
  fetchFeedbackStats,
  type CostAggregationResponse,
  type ProviderStatus,
  type FeedbackStats,
} from "@/lib/api";
import { useSessionEvents } from "@/hooks/use-session-events";

// Format currency with precision
function formatCurrency(value: number): string {
  if (value < 0.01) return `$${value.toFixed(4)}`;
  if (value < 1) return `$${value.toFixed(3)}`;
  return `$${value.toFixed(2)}`;
}

// Format large numbers
function formatNumber(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString();
}

// Format uptime
function formatUptime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 24) {
    const days = Math.floor(hours / 24);
    return `${days}d ${hours % 24}h`;
  }
  return `${hours}h ${minutes}m`;
}

// KPI Card Component
function KPICard({
  title,
  value,
  subtitle,
  icon: Icon,
  trend,
  status,
}: {
  title: string;
  value: string;
  subtitle?: string;
  icon: React.ComponentType<{ className?: string }>;
  trend?: { value: number; label: string };
  status?: "success" | "warning" | "error" | "neutral";
}) {
  const statusColors = {
    success: "border-l-emerald-500",
    warning: "border-l-amber-500",
    error: "border-l-red-500",
    neutral: "border-l-slate-400 dark:border-l-slate-600",
  };

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800",
        "bg-white dark:bg-slate-900/50 backdrop-blur-sm",
        "border-l-4",
        statusColors[status || "neutral"],
        "transition-all duration-300 hover:shadow-lg hover:shadow-slate-200/50 dark:hover:shadow-slate-900/50",
        "group",
      )}
    >
      {/* Subtle grid pattern overlay */}
      <div className="absolute inset-0 opacity-[0.02] dark:opacity-[0.05] pointer-events-none">
        <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <pattern
              id="grid"
              width="20"
              height="20"
              patternUnits="userSpaceOnUse"
            >
              <path
                d="M 20 0 L 0 0 0 20"
                fill="none"
                stroke="currentColor"
                strokeWidth="0.5"
              />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />
        </svg>
      </div>

      <div className="relative p-5">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
              {title}
            </p>
            <p className="mt-2 text-3xl font-light tracking-tight text-slate-900 dark:text-slate-100 font-mono">
              {value}
            </p>
            {subtitle && (
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {subtitle}
              </p>
            )}
            {trend && (
              <div className="mt-2 flex items-center gap-1">
                <TrendingUp
                  className={cn(
                    "h-3 w-3",
                    trend.value >= 0
                      ? "text-emerald-500"
                      : "text-red-500 rotate-180",
                  )}
                />
                <span
                  className={cn(
                    "text-xs font-medium",
                    trend.value >= 0
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-red-600 dark:text-red-400",
                  )}
                >
                  {trend.value >= 0 ? "+" : ""}
                  {trend.value}% {trend.label}
                </span>
              </div>
            )}
          </div>
          <div
            className={cn(
              "p-2.5 rounded-lg",
              "bg-slate-100 dark:bg-slate-800",
              "group-hover:scale-110 transition-transform duration-300",
            )}
          >
            <Icon className="h-5 w-5 text-slate-600 dark:text-slate-400" />
          </div>
        </div>
      </div>
    </div>
  );
}

// Provider Status Card
function ProviderCard({ provider }: { provider: ProviderStatus }) {
  const health = provider.health;
  const state =
    health?.state || (provider.available ? "healthy" : "unavailable");

  const stateConfig = {
    healthy: {
      icon: CheckCircle2,
      color: "text-emerald-500",
      bg: "bg-emerald-500/10",
      label: "Operational",
    },
    degraded: {
      icon: AlertTriangle,
      color: "text-amber-500",
      bg: "bg-amber-500/10",
      label: "Degraded",
    },
    unavailable: {
      icon: XCircle,
      color: "text-red-500",
      bg: "bg-red-500/10",
      label: "Unavailable",
    },
    unknown: {
      icon: Clock,
      color: "text-slate-400",
      bg: "bg-slate-400/10",
      label: "Unknown",
    },
  };

  const config = stateConfig[state] || stateConfig.unknown;
  const StatusIcon = config.icon;

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-lg border border-slate-200 dark:border-slate-800",
        "bg-white dark:bg-slate-900/50 backdrop-blur-sm",
        "p-4 transition-all duration-300",
      )}
    >
      <div className="flex items-center gap-3">
        <div className={cn("p-2 rounded-lg", config.bg)}>
          {provider.name === "claude" ? (
            <Cpu className="h-5 w-5 text-orange-600 dark:text-orange-400" />
          ) : (
            <Server className="h-5 w-5 text-blue-600 dark:text-blue-400" />
          )}
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h3 className="font-medium text-slate-900 dark:text-slate-100 capitalize">
              {provider.name}
            </h3>
            <div
              className={cn(
                "flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium",
                config.bg,
                config.color,
              )}
            >
              <StatusIcon className="h-3 w-3" />
              <span>{config.label}</span>
            </div>
          </div>
          {health && (
            <div className="mt-2 flex items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
              <span>Latency: {health.latency_ms.toFixed(0)}ms</span>
              <span>
                Availability: {(health.availability * 100).toFixed(1)}%
              </span>
            </div>
          )}
          {provider.error && (
            <p className="mt-1 text-xs text-red-500 truncate">
              {provider.error}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// Simple Line Chart (CSS-based)
function MiniChart({ data, label }: { data: number[]; label: string }) {
  if (data.length === 0) return null;

  const max = Math.max(...data, 1);
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * 100;
      const y = 100 - (v / max) * 100;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div className="relative h-32">
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="w-full h-full"
      >
        {/* Grid lines */}
        <g className="text-slate-200 dark:text-slate-800">
          {[0, 25, 50, 75, 100].map((y) => (
            <line
              key={y}
              x1="0"
              y1={y}
              x2="100"
              y2={y}
              stroke="currentColor"
              strokeWidth="0.5"
              strokeDasharray="2,2"
            />
          ))}
        </g>
        {/* Area fill */}
        <polygon
          points={`0,100 ${points} 100,100`}
          className="fill-emerald-500/10 dark:fill-emerald-400/10"
        />
        {/* Line */}
        <polyline
          points={points}
          fill="none"
          className="stroke-emerald-500 dark:stroke-emerald-400"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {/* End dot */}
        {data.length > 0 && (
          <circle
            cx={100}
            cy={100 - (data[data.length - 1] / max) * 100}
            r="3"
            className="fill-emerald-500 dark:fill-emerald-400"
          />
        )}
      </svg>
      <div className="absolute bottom-0 left-0 right-0 flex justify-between text-[10px] text-slate-400 pt-1">
        <span>7d ago</span>
        <span>{label}</span>
        <span>Today</span>
      </div>
    </div>
  );
}

// Cost by Model Bar Chart
function ModelBreakdownChart({
  data,
}: {
  data: CostAggregationResponse | undefined;
}) {
  if (!data || data.aggregations.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-slate-400 text-sm">
        No data available
      </div>
    );
  }

  const total = data.total_cost_usd || 1;
  const sorted = [...data.aggregations].sort(
    (a, b) => b.total_cost_usd - a.total_cost_usd,
  );

  const colors = [
    "bg-orange-500 dark:bg-orange-400",
    "bg-blue-500 dark:bg-blue-400",
    "bg-emerald-500 dark:bg-emerald-400",
    "bg-purple-500 dark:bg-purple-400",
    "bg-rose-500 dark:bg-rose-400",
  ];

  return (
    <div className="space-y-3">
      {sorted.slice(0, 5).map((item, idx) => {
        const percent = (item.total_cost_usd / total) * 100;
        const modelName = item.group_key
          .replace("claude-", "")
          .replace("gemini-", "");

        return (
          <div key={item.group_key} className="group">
            <div className="flex items-center justify-between text-sm mb-1">
              <span className="text-slate-600 dark:text-slate-400 truncate max-w-[60%] font-mono text-xs">
                {modelName}
              </span>
              <span className="text-slate-900 dark:text-slate-100 font-medium font-mono">
                {formatCurrency(item.total_cost_usd)}
              </span>
            </div>
            <div className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-500 ease-out",
                  colors[idx % colors.length],
                )}
                style={{ width: `${Math.max(percent, 2)}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Main Dashboard
export default function DashboardPage() {
  // Real-time events for active session count
  const { events } = useSessionEvents({ autoConnect: true });

  // Calculate active session count from recent events
  const activeSessionCount = useMemo(() => {
    const now = Date.now();
    const recentEvents = events.filter(
      (e) => now - new Date(e.timestamp).getTime() < 60000,
    );
    const activeSessions = new Set(recentEvents.map((e) => e.session_id));
    return activeSessions.size;
  }, [events]);

  const {
    data: status,
    isLoading: statusLoading,
    error: statusError,
  } = useQuery({
    queryKey: ["status"],
    queryFn: fetchStatus,
    refetchInterval: 30000, // Refresh every 30s
  });

  const { data: dailyCosts, isLoading: dailyLoading } = useQuery({
    queryKey: ["costs", "day", 7],
    queryFn: () => fetchCosts({ group_by: "day", days: 7 }),
    refetchInterval: 60000, // Refresh every minute
  });

  const { data: modelCosts, isLoading: modelLoading } = useQuery({
    queryKey: ["costs", "model", 7],
    queryFn: () => fetchCosts({ group_by: "model", days: 7 }),
    refetchInterval: 60000,
  });

  const { data: totalCosts } = useQuery({
    queryKey: ["costs", "none", 7],
    queryFn: () => fetchCosts({ group_by: "none", days: 7 }),
    refetchInterval: 60000,
  });

  const { data: feedbackStats, isLoading: feedbackLoading } = useQuery({
    queryKey: ["feedbackStats", 7],
    queryFn: () => fetchFeedbackStats({ days: 7 }),
    refetchInterval: 60000,
  });

  // Extract chart data
  const requestsByDay =
    dailyCosts?.aggregations.map((a) => a.request_count) || [];

  // Calculate error rate (mock for now - would need real error tracking)
  const errorRate = status?.providers.some((p) => !p.available) ? 5.2 : 0.1;

  // Calculate satisfaction rate from feedback
  const satisfactionRate = feedbackStats?.total_feedback
    ? feedbackStats.positive_rate * 100
    : null;

  // Determine overall status
  const overallStatus =
    status?.status === "healthy"
      ? "success"
      : status?.status === "degraded"
        ? "warning"
        : "neutral";

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Page Header */}
      <header className="sticky top-0 z-10 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              Dashboard
            </h1>
            <div className="flex items-center gap-4">
              {status && (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-100 dark:bg-slate-800">
                  <div
                    className={cn(
                      "w-2 h-2 rounded-full",
                      status.status === "healthy"
                        ? "bg-emerald-500"
                        : "bg-amber-500",
                    )}
                  />
                  <span className="text-sm text-slate-600 dark:text-slate-400 capitalize">
                    {status.status}
                  </span>
                </div>
              )}
              <div className="text-xs text-slate-400 font-mono">
                {status ? formatUptime(status.uptime_seconds) : "--"} uptime
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-8">
        {/* Error state */}
        {statusError && (
          <div className="mb-6 p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
            <p className="text-sm text-red-600 dark:text-red-400">
              Failed to load dashboard data. Backend may be unavailable.
            </p>
          </div>
        )}

        {/* KPI Cards */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <KPICard
            title="Active Sessions"
            value={String(activeSessionCount)}
            subtitle="Currently running"
            icon={Activity}
            status={activeSessionCount > 0 ? "success" : overallStatus}
          />
          <KPICard
            title="Total Cost"
            value={
              dailyLoading
                ? "..."
                : formatCurrency(totalCosts?.total_cost_usd || 0)
            }
            subtitle="Last 7 days"
            icon={DollarSign}
            status="neutral"
          />
          <KPICard
            title="Requests"
            value={
              dailyLoading
                ? "..."
                : formatNumber(totalCosts?.total_requests || 0)
            }
            subtitle="Last 7 days"
            icon={Zap}
            status="success"
          />
          <KPICard
            title="Error Rate"
            value={`${errorRate.toFixed(1)}%`}
            subtitle="Last 7 days"
            icon={AlertTriangle}
            status={
              errorRate < 1 ? "success" : errorRate < 5 ? "warning" : "error"
            }
          />
        </section>

        {/* Charts and Providers */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Requests over time */}
          <div className="lg:col-span-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/50 p-6">
            <h2 className="text-sm font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-4">
              Requests Over Time
            </h2>
            {dailyLoading ? (
              <div className="h-32 flex items-center justify-center text-slate-400">
                Loading...
              </div>
            ) : (
              <MiniChart data={requestsByDay} label="requests" />
            )}
          </div>

          {/* Provider Status */}
          <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/50 p-6">
            <h2 className="text-sm font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-4">
              Provider Status
            </h2>
            <div className="space-y-3">
              {statusLoading ? (
                <div className="h-32 flex items-center justify-center text-slate-400">
                  Loading...
                </div>
              ) : status?.providers ? (
                status.providers.map((provider) => (
                  <ProviderCard key={provider.name} provider={provider} />
                ))
              ) : (
                <p className="text-sm text-slate-400">
                  No providers configured
                </p>
              )}
            </div>
          </div>

          {/* Cost by Model */}
          <div className="lg:col-span-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/50 p-6">
            <h2 className="text-sm font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-4">
              Cost by Model
            </h2>
            {modelLoading ? (
              <div className="h-32 flex items-center justify-center text-slate-400">
                Loading...
              </div>
            ) : (
              <ModelBreakdownChart data={modelCosts} />
            )}
          </div>

          {/* Token Usage Summary */}
          <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/50 p-6">
            <h2 className="text-sm font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-4">
              Token Usage
            </h2>
            <div className="space-y-4">
              <div>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Total Tokens
                </p>
                <p className="text-2xl font-light font-mono text-slate-900 dark:text-slate-100">
                  {formatNumber(totalCosts?.total_tokens || 0)}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-4 pt-4 border-t border-slate-100 dark:border-slate-800">
                <div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Input
                  </p>
                  <p className="text-lg font-mono text-slate-700 dark:text-slate-300">
                    {formatNumber(
                      modelCosts?.aggregations.reduce(
                        (sum, a) => sum + a.input_tokens,
                        0,
                      ) || 0,
                    )}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Output
                  </p>
                  <p className="text-lg font-mono text-slate-700 dark:text-slate-300">
                    {formatNumber(
                      modelCosts?.aggregations.reduce(
                        (sum, a) => sum + a.output_tokens,
                        0,
                      ) || 0,
                    )}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* User Feedback Summary */}
          <div className="lg:col-span-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/50 p-6">
            <h2 className="text-sm font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-4">
              User Feedback
            </h2>
            {feedbackLoading ? (
              <div className="h-24 flex items-center justify-center text-slate-400">
                Loading...
              </div>
            ) : feedbackStats?.total_feedback === 0 ? (
              <div className="h-24 flex items-center justify-center text-slate-400">
                No feedback collected yet
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-4 gap-6">
                {/* Satisfaction Rate */}
                <div className="flex flex-col items-center justify-center p-4 rounded-lg bg-slate-50 dark:bg-slate-800/50">
                  <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
                    Satisfaction Rate
                  </p>
                  <p
                    className={cn(
                      "text-3xl font-light font-mono",
                      satisfactionRate && satisfactionRate >= 80
                        ? "text-emerald-600 dark:text-emerald-400"
                        : satisfactionRate && satisfactionRate >= 60
                          ? "text-amber-600 dark:text-amber-400"
                          : "text-red-600 dark:text-red-400",
                    )}
                  >
                    {satisfactionRate !== null
                      ? `${satisfactionRate.toFixed(0)}%`
                      : "--"}
                  </p>
                </div>

                {/* Positive/Negative Split */}
                <div className="flex flex-col gap-3 p-4 rounded-lg bg-slate-50 dark:bg-slate-800/50">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <ThumbsUp className="h-4 w-4 text-emerald-500" />
                      <span className="text-sm text-slate-600 dark:text-slate-400">
                        Positive
                      </span>
                    </div>
                    <span className="font-mono text-lg text-slate-900 dark:text-slate-100">
                      {feedbackStats?.positive_count || 0}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <ThumbsDown className="h-4 w-4 text-red-500" />
                      <span className="text-sm text-slate-600 dark:text-slate-400">
                        Negative
                      </span>
                    </div>
                    <span className="font-mono text-lg text-slate-900 dark:text-slate-100">
                      {feedbackStats?.negative_count || 0}
                    </span>
                  </div>
                </div>

                {/* Total Feedback */}
                <div className="flex flex-col items-center justify-center p-4 rounded-lg bg-slate-50 dark:bg-slate-800/50">
                  <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
                    Total Responses
                  </p>
                  <p className="text-3xl font-light font-mono text-slate-900 dark:text-slate-100">
                    {feedbackStats?.total_feedback || 0}
                  </p>
                </div>

                {/* Top Issue Categories */}
                <div className="p-4 rounded-lg bg-slate-50 dark:bg-slate-800/50">
                  <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
                    Top Issues
                  </p>
                  {feedbackStats?.categories &&
                  Object.keys(feedbackStats.categories).length > 0 ? (
                    <div className="space-y-1">
                      {Object.entries(feedbackStats.categories)
                        .sort(([, a], [, b]) => b - a)
                        .slice(0, 3)
                        .map(([category, count]) => (
                          <div
                            key={category}
                            className="flex items-center justify-between text-sm"
                          >
                            <span className="text-slate-600 dark:text-slate-400 capitalize truncate">
                              {category}
                            </span>
                            <span className="font-mono text-slate-900 dark:text-slate-100">
                              {count}
                            </span>
                          </div>
                        ))}
                    </div>
                  ) : (
                    <p className="text-sm text-slate-400">No issues reported</p>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
