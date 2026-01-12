"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  DollarSign,
  Cpu,
  TrendingUp,
  Activity,
  Layers,
  Calendar,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchCosts, fetchTruncations, type CostAggregation } from "@/lib/api";
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

// Color palettes
const PIE_COLORS = [
  "#f59e0b", // amber-500
  "#3b82f6", // blue-500
  "#10b981", // emerald-500
  "#8b5cf6", // violet-500
  "#ec4899", // pink-500
  "#06b6d4", // cyan-500
];

const BAR_COLORS = {
  input: "#10b981", // emerald
  output: "#3b82f6", // blue
};

function formatCost(cost: number): string {
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  if (cost < 1) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(2)}`;
}

function formatTokens(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
  return tokens.toString();
}

function formatDateKey(key: string): string {
  const date = new Date(key);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

type DateRange = "7" | "14" | "30" | "90";

export default function AnalyticsPage() {
  const [dateRange, setDateRange] = useState<DateRange>("30");
  const days = parseInt(dateRange);

  // Fetch costs by project
  const { data: costsByProject, isLoading: loadingByProject } = useQuery({
    queryKey: ["costs", "project", days],
    queryFn: () => fetchCosts({ group_by: "project", days }),
  });

  // Fetch costs by day
  const { data: costsByDay, isLoading: loadingByDay } = useQuery({
    queryKey: ["costs", "day", days],
    queryFn: () => fetchCosts({ group_by: "day", days }),
  });

  // Fetch costs by model
  const { data: costsByModel, isLoading: loadingByModel } = useQuery({
    queryKey: ["costs", "model", days],
    queryFn: () => fetchCosts({ group_by: "model", days }),
  });

  // Fetch truncation metrics
  const { data: truncations, isLoading: loadingTruncations } = useQuery({
    queryKey: ["truncations", days],
    queryFn: () =>
      fetchTruncations({ days, include_recent: true, limit_recent: 5 }),
  });

  const isLoading =
    loadingByProject || loadingByDay || loadingByModel || loadingTruncations;

  // Prepare pie chart data
  const pieData =
    costsByProject?.aggregations.map((agg: CostAggregation) => ({
      name: agg.group_key,
      value: agg.total_cost_usd,
      tokens: agg.total_tokens,
      requests: agg.request_count,
    })) || [];

  // Prepare line chart data
  const lineData =
    costsByDay?.aggregations.map((agg: CostAggregation) => ({
      date: formatDateKey(agg.group_key),
      cost: agg.total_cost_usd,
      tokens: agg.total_tokens,
    })) || [];

  // Prepare bar chart data
  const barData =
    costsByModel?.aggregations.map((agg: CostAggregation) => ({
      model: agg.group_key.replace("claude-", "").replace("gemini-", "g-"),
      input: agg.input_tokens,
      output: agg.output_tokens,
      cost: agg.total_cost_usd,
    })) || [];

  // Calculate efficiency metrics
  const totalTokens = costsByProject?.total_tokens || 0;
  const totalRequests = costsByProject?.total_requests || 0;
  const avgTokensPerRequest =
    totalRequests > 0 ? Math.round(totalTokens / totalRequests) : 0;
  const truncationRate = truncations?.truncation_rate || 0;
  const totalTruncations = truncations?.total_truncations || 0;

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Page Header */}
      <header className="sticky top-0 z-10 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-3">
              <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                Analytics
              </h1>
              <span className="text-sm text-slate-500 dark:text-slate-400">
                Cost & usage insights
              </span>
            </div>

            {/* Date Range Selector */}
            <div className="flex items-center gap-2">
              <Calendar className="h-4 w-4 text-slate-400" />
              <select
                data-testid="date-range-select"
                value={dateRange}
                onChange={(e) => setDateRange(e.target.value as DateRange)}
                className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="7">Last 7 days</option>
                <option value="14">Last 14 days</option>
                <option value="30">Last 30 days</option>
                <option value="90">Last 90 days</option>
              </select>

              {isLoading && (
                <RefreshCw className="h-4 w-4 text-slate-400 animate-spin" />
              )}
            </div>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-8">
        {/* Summary Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <SummaryCard
            data-testid="total-cost-card"
            icon={DollarSign}
            label="Total Cost"
            value={formatCost(costsByProject?.total_cost_usd || 0)}
            trend={`${days} days`}
            trendUp={false}
          />
          <SummaryCard
            data-testid="total-tokens-card"
            icon={Cpu}
            label="Total Tokens"
            value={formatTokens(totalTokens)}
            trend={`${formatTokens(avgTokensPerRequest)}/req avg`}
            trendUp={false}
          />
          <SummaryCard
            data-testid="total-requests-card"
            icon={TrendingUp}
            label="Total Requests"
            value={totalRequests.toLocaleString()}
            trend={`${(totalRequests / days).toFixed(1)}/day avg`}
            trendUp={false}
          />
          <SummaryCard
            data-testid="truncation-rate-card"
            icon={Activity}
            label="Truncation Rate"
            value={`${truncationRate.toFixed(1)}%`}
            trend={`${totalTruncations} events`}
            trendUp={truncationRate > 5}
            trendColor={truncationRate > 5 ? "red" : "green"}
          />
        </div>

        {/* Charts Row 1 */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* Cost by Project Pie Chart */}
          <div
            data-testid="cost-by-project-chart"
            className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 p-6"
          >
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100 mb-4 flex items-center gap-2">
              <Layers className="h-4 w-4 text-amber-500" />
              Cost by Project
            </h3>
            {pieData.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    labelLine={false}
                    label={({ name, percent }) =>
                      `${name} ${((percent ?? 0) * 100).toFixed(0)}%`
                    }
                    outerRadius={100}
                    fill="#8884d8"
                    dataKey="value"
                  >
                    {pieData.map((_, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={PIE_COLORS[index % PIE_COLORS.length]}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value) => formatCost(Number(value))}
                    contentStyle={{
                      backgroundColor: "var(--slate-800)",
                      border: "none",
                      borderRadius: "8px",
                    }}
                  />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState message="No cost data available" />
            )}
          </div>

          {/* Daily Spend Line Chart */}
          <div
            data-testid="daily-spend-chart"
            className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 p-6"
          >
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100 mb-4 flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-blue-500" />
              Daily Spend
            </h3>
            {lineData.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={lineData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis
                    dataKey="date"
                    tick={{ fill: "#9ca3af", fontSize: 12 }}
                  />
                  <YAxis
                    tick={{ fill: "#9ca3af", fontSize: 12 }}
                    tickFormatter={(v) => `$${v.toFixed(2)}`}
                  />
                  <Tooltip
                    formatter={(value) => formatCost(Number(value))}
                    contentStyle={{
                      backgroundColor: "#1e293b",
                      border: "none",
                      borderRadius: "8px",
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="cost"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={{ fill: "#3b82f6", r: 4 }}
                    activeDot={{ r: 6 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState message="No daily data available" />
            )}
          </div>
        </div>

        {/* Charts Row 2 */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* Model Usage Bar Chart */}
          <div
            data-testid="model-usage-chart"
            className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 p-6"
          >
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100 mb-4 flex items-center gap-2">
              <Cpu className="h-4 w-4 text-emerald-500" />
              Model Usage (Tokens)
            </h3>
            {barData.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={barData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis
                    dataKey="model"
                    tick={{ fill: "#9ca3af", fontSize: 11 }}
                    angle={-15}
                    textAnchor="end"
                  />
                  <YAxis
                    tick={{ fill: "#9ca3af", fontSize: 12 }}
                    tickFormatter={(v) => formatTokens(v)}
                  />
                  <Tooltip
                    formatter={(value) => formatTokens(Number(value))}
                    contentStyle={{
                      backgroundColor: "#1e293b",
                      border: "none",
                      borderRadius: "8px",
                    }}
                  />
                  <Legend />
                  <Bar dataKey="input" name="Input" fill={BAR_COLORS.input} />
                  <Bar
                    dataKey="output"
                    name="Output"
                    fill={BAR_COLORS.output}
                  />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState message="No model data available" />
            )}
          </div>

          {/* Token Efficiency */}
          <div
            data-testid="token-efficiency-section"
            className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 p-6"
          >
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100 mb-4 flex items-center gap-2">
              <Activity className="h-4 w-4 text-violet-500" />
              Efficiency Metrics
            </h3>

            <div className="space-y-6">
              {/* Avg Tokens per Request */}
              <div>
                <div className="flex justify-between text-sm mb-2">
                  <span className="text-slate-600 dark:text-slate-400">
                    Avg Tokens per Request
                  </span>
                  <span className="font-medium text-slate-900 dark:text-slate-100">
                    {formatTokens(avgTokensPerRequest)}
                  </span>
                </div>
                <div className="h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-violet-500 rounded-full"
                    style={{
                      width: `${Math.min(100, (avgTokensPerRequest / 10000) * 100)}%`,
                    }}
                  />
                </div>
              </div>

              {/* Truncation Rate Gauge */}
              <div>
                <div className="flex justify-between text-sm mb-2">
                  <span className="text-slate-600 dark:text-slate-400">
                    Truncation Rate
                  </span>
                  <span
                    className={cn(
                      "font-medium",
                      truncationRate > 10
                        ? "text-red-500"
                        : truncationRate > 5
                          ? "text-amber-500"
                          : "text-emerald-500",
                    )}
                  >
                    {truncationRate.toFixed(1)}%
                  </span>
                </div>
                <div className="h-2 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full",
                      truncationRate > 10
                        ? "bg-red-500"
                        : truncationRate > 5
                          ? "bg-amber-500"
                          : "bg-emerald-500",
                    )}
                    style={{ width: `${Math.min(100, truncationRate)}%` }}
                  />
                </div>
              </div>

              {/* Cost Efficiency (cost per 1K tokens) */}
              <div>
                <div className="flex justify-between text-sm mb-2">
                  <span className="text-slate-600 dark:text-slate-400">
                    Cost per 1K Tokens
                  </span>
                  <span className="font-medium text-slate-900 dark:text-slate-100">
                    {totalTokens > 0
                      ? formatCost(
                          ((costsByProject?.total_cost_usd || 0) /
                            totalTokens) *
                            1000,
                        )
                      : "$0.00"}
                  </span>
                </div>
              </div>

              {/* Recent truncation events */}
              {truncations?.recent_events &&
                truncations.recent_events.length > 0 && (
                  <div className="pt-4 border-t border-slate-200 dark:border-slate-700">
                    <h4 className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-2">
                      Recent Truncations
                    </h4>
                    <div className="space-y-2">
                      {truncations.recent_events.slice(0, 3).map((event) => (
                        <div
                          key={event.id}
                          className="flex items-center justify-between text-xs"
                        >
                          <span className="text-slate-600 dark:text-slate-400 truncate">
                            {event.model
                              .replace("claude-", "")
                              .replace("gemini-", "g-")}
                          </span>
                          <span className="text-slate-500 dark:text-slate-500">
                            {formatTokens(event.output_tokens)} /{" "}
                            {formatTokens(event.max_tokens_requested)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
            </div>
          </div>
        </div>

        {/* Error/Loading States */}
        {!isLoading && !costsByProject?.aggregations?.length && (
          <div className="flex items-center gap-2 p-4 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-amber-600 dark:text-amber-400">
            <AlertCircle className="h-5 w-5" />
            <p className="text-sm">
              No analytics data found for the selected time period. Make some
              API requests to see data here.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}

interface SummaryCardProps {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  trend: string;
  trendUp: boolean;
  trendColor?: "green" | "red";
  "data-testid"?: string;
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  trend,
  trendColor,
  "data-testid": testId,
}: SummaryCardProps) {
  return (
    <div
      data-testid={testId}
      className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 p-4"
    >
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800">
          <Icon className="h-5 w-5 text-slate-600 dark:text-slate-400" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
          <p className="text-xl font-semibold text-slate-900 dark:text-slate-100">
            {value}
          </p>
        </div>
      </div>
      <p
        className={cn(
          "text-xs mt-2",
          trendColor === "red"
            ? "text-red-500"
            : trendColor === "green"
              ? "text-emerald-500"
              : "text-slate-500 dark:text-slate-400",
        )}
      >
        {trend}
      </p>
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-[300px] text-slate-400">
      <p className="text-sm">{message}</p>
    </div>
  );
}
