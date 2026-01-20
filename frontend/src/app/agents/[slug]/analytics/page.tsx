"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  ArrowLeft,
  DollarSign,
  Clock,
  AlertTriangle,
  Zap,
  RefreshCw,
  ExternalLink,
  Loader2,
  AlertCircle,
  TrendingUp,
  TrendingDown,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  PieChart,
  Pie,
} from "recharts";
import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

interface Agent {
  id: number;
  slug: string;
  name: string;
  primary_model_id: string;
  fallback_models: string[];
}

interface AnalyticsData {
  total_cost_usd: number;
  avg_latency_ms: number;
  error_rate: number;
  cache_hit_rate: number;
  total_requests: number;
  model_distribution: { model: string; count: number; percentage: number }[];
  latency_histogram: { range: string; count: number }[];
  recent_failures: {
    id: string;
    timestamp: string;
    error_type: string;
    message: string;
    model: string;
  }[];
  trend: {
    cost_change: number;
    latency_change: number;
    error_change: number;
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// MOCK DATA (until real analytics API is implemented)
// ─────────────────────────────────────────────────────────────────────────────

function generateMockAnalytics(agent: Agent): AnalyticsData {
  // Generate consistent mock data based on agent slug
  const hash = agent.slug.split("").reduce((acc, char) => acc + char.charCodeAt(0), 0);
  const baseRequests = (hash % 500) + 100;

  return {
    total_cost_usd: parseFloat(((hash % 100) * 0.15).toFixed(2)),
    avg_latency_ms: 800 + (hash % 400),
    error_rate: parseFloat(((hash % 10) * 0.5).toFixed(1)),
    cache_hit_rate: 60 + (hash % 30),
    total_requests: baseRequests,
    model_distribution: [
      { model: agent.primary_model_id, count: Math.floor(baseRequests * 0.7), percentage: 70 },
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
    recent_failures: (hash % 3) === 0 ? [] : [
      {
        id: `err-${hash}-1`,
        timestamp: new Date(Date.now() - 3600000).toISOString(),
        error_type: "rate_limit",
        message: "Rate limit exceeded for model",
        model: agent.primary_model_id,
      },
      {
        id: `err-${hash}-2`,
        timestamp: new Date(Date.now() - 7200000).toISOString(),
        error_type: "timeout",
        message: "Request timed out after 30s",
        model: agent.fallback_models[0] || agent.primary_model_id,
      },
    ],
    trend: {
      cost_change: -12.5 + (hash % 25),
      latency_change: -5 + (hash % 20),
      error_change: -2 + (hash % 8),
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// API
// ─────────────────────────────────────────────────────────────────────────────

async function fetchAgent(slug: string): Promise<Agent> {
  const res = await fetch(`/api/agents/${slug}`);
  if (!res.ok) throw new Error("Failed to fetch agent");
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPONENTS
// ─────────────────────────────────────────────────────────────────────────────

const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"];

function KPICard({
  label,
  value,
  unit,
  icon: Icon,
  trend,
  color = "blue",
}: {
  label: string;
  value: string | number;
  unit?: string;
  icon: React.ElementType;
  trend?: number;
  color?: "blue" | "green" | "amber" | "red";
}) {
  const colorClasses = {
    blue: "bg-blue-50 dark:bg-blue-950/30 text-blue-600 dark:text-blue-400",
    green: "bg-emerald-50 dark:bg-emerald-950/30 text-emerald-600 dark:text-emerald-400",
    amber: "bg-amber-50 dark:bg-amber-950/30 text-amber-600 dark:text-amber-400",
    red: "bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400",
  };

  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-1">
            {label}
          </p>
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-bold text-slate-900 dark:text-slate-100 tabular-nums">
              {value}
            </span>
            {unit && (
              <span className="text-sm text-slate-500 dark:text-slate-400">
                {unit}
              </span>
            )}
          </div>
          {trend !== undefined && (
            <div
              className={cn(
                "flex items-center gap-1 mt-1 text-xs font-medium",
                trend >= 0 ? "text-red-500" : "text-emerald-500"
              )}
            >
              {trend >= 0 ? (
                <TrendingUp className="h-3 w-3" />
              ) : (
                <TrendingDown className="h-3 w-3" />
              )}
              {Math.abs(trend).toFixed(1)}% vs last 7d
            </div>
          )}
        </div>
        <div className={cn("p-2.5 rounded-lg", colorClasses[color])}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  );
}

function ChartCard({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-5">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-4">
        {title}
      </h3>
      {children}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN PAGE
// ─────────────────────────────────────────────────────────────────────────────

export default function AgentAnalyticsPage() {
  const params = useParams();
  const router = useRouter();
  const slug = params.slug as string;

  const [timeRange, setTimeRange] = useState("7d");

  const { data: agent, isLoading, error } = useQuery({
    queryKey: ["agent", slug],
    queryFn: () => fetchAgent(slug),
    enabled: !!slug,
  });

  // Generate mock analytics based on agent
  const analytics = agent ? generateMockAnalytics(agent) : null;

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    );
  }

  if (error || !agent || !analytics) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="h-10 w-10 text-red-500 mx-auto mb-3" />
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Agent not found
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* HEADER */}
      <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-4">
              <button
                onClick={() => router.push(`/agents/${slug}`)}
                className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                <ArrowLeft className="h-5 w-5 text-slate-600 dark:text-slate-400" />
              </button>
              <div className="flex items-center gap-2">
                <Bot className="h-5 w-5 text-slate-600 dark:text-slate-400" />
                <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100 tracking-tight">
                  {agent.name}
                </h1>
                <span className="text-xs font-medium text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">
                  Analytics
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <select
                value={timeRange}
                onChange={(e) => setTimeRange(e.target.value)}
                className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-blue-500/40"
              >
                <option value="24h">Last 24 hours</option>
                <option value="7d">Last 7 days</option>
                <option value="30d">Last 30 days</option>
              </select>
              <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors">
                <RefreshCw className="h-3.5 w-3.5" />
                Refresh
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* CONTENT */}
      <main className="p-6 lg:p-8 max-w-7xl mx-auto">
        {/* KPI CARDS */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <KPICard
            label="Total Cost"
            value={`$${analytics.total_cost_usd.toFixed(2)}`}
            icon={DollarSign}
            trend={analytics.trend.cost_change}
            color="blue"
          />
          <KPICard
            label="Avg Latency"
            value={analytics.avg_latency_ms}
            unit="ms"
            icon={Clock}
            trend={analytics.trend.latency_change}
            color="amber"
          />
          <KPICard
            label="Error Rate"
            value={`${analytics.error_rate}%`}
            icon={AlertTriangle}
            trend={analytics.trend.error_change}
            color="red"
          />
          <KPICard
            label="Cache Hit Rate"
            value={`${analytics.cache_hit_rate}%`}
            icon={Zap}
            color="green"
          />
        </div>

        {/* CHARTS ROW */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* Model Distribution */}
          <ChartCard title="Model Load Distribution">
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={analytics.model_distribution}
                    dataKey="count"
                    nameKey="model"
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={90}
                    paddingAngle={2}
                    label={({ name, percent }) =>
                      name && percent !== undefined ? `${String(name).split("-").slice(0, 2).join("-")} (${(percent * 100).toFixed(0)}%)` : ""
                    }
                    labelLine={false}
                  >
                    {analytics.model_distribution.map((_, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={COLORS[index % COLORS.length]}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value) => [
                      `${value} requests`,
                      "Count",
                    ]}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>

          {/* Latency Histogram */}
          <ChartCard title="Latency Distribution">
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={analytics.latency_histogram}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis
                    dataKey="range"
                    tick={{ fontSize: 11 }}
                    stroke="#94a3b8"
                  />
                  <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" />
                  <Tooltip
                    formatter={(value) => [`${value} requests`, "Count"]}
                    contentStyle={{
                      backgroundColor: "#1e293b",
                      border: "none",
                      borderRadius: "8px",
                      fontSize: "12px",
                    }}
                  />
                  <Bar
                    dataKey="count"
                    fill="#3b82f6"
                    radius={[4, 4, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>
        </div>

        {/* RECENT FAILURES TABLE */}
        <ChartCard title="Recent Failures">
          {analytics.recent_failures.length === 0 ? (
            <div className="py-8 text-center">
              <div className="w-12 h-12 rounded-full bg-emerald-50 dark:bg-emerald-950/30 flex items-center justify-center mx-auto mb-3">
                <Zap className="h-6 w-6 text-emerald-500" />
              </div>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                No failures in the selected time range
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-200 dark:border-slate-700">
                    <th className="text-left text-[10px] font-bold uppercase tracking-wider text-slate-500 py-2">
                      Time
                    </th>
                    <th className="text-left text-[10px] font-bold uppercase tracking-wider text-slate-500 py-2">
                      Error Type
                    </th>
                    <th className="text-left text-[10px] font-bold uppercase tracking-wider text-slate-500 py-2">
                      Message
                    </th>
                    <th className="text-left text-[10px] font-bold uppercase tracking-wider text-slate-500 py-2">
                      Model
                    </th>
                    <th className="text-right text-[10px] font-bold uppercase tracking-wider text-slate-500 py-2">
                      Action
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {analytics.recent_failures.map((failure) => (
                    <tr
                      key={failure.id}
                      className="border-b border-slate-100 dark:border-slate-800 last:border-0"
                    >
                      <td className="py-3 text-xs text-slate-600 dark:text-slate-400 font-mono">
                        {new Date(failure.timestamp).toLocaleString()}
                      </td>
                      <td className="py-3">
                        <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400">
                          {failure.error_type}
                        </span>
                      </td>
                      <td className="py-3 text-xs text-slate-700 dark:text-slate-300">
                        {failure.message}
                      </td>
                      <td className="py-3 text-xs text-slate-500 font-mono">
                        {failure.model}
                      </td>
                      <td className="py-3 text-right">
                        <a
                          href={`/sessions?error=${failure.id}`}
                          className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
                        >
                          View Trace
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </ChartCard>

        {/* Note about mock data */}
        <p className="mt-6 text-center text-xs text-slate-400">
          Analytics data is simulated. Real metrics will be available when agent usage tracking is implemented.
        </p>
      </main>
    </div>
  );
}
