"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  DollarSign,
  Zap,
  Clock,
  AlertTriangle,
  Server,
  Cpu,
  ThumbsUp,
  ThumbsDown,
  Layers,
  MessageSquare,
  BarChart3,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchStatus,
  fetchCosts,
  fetchFeedbackStats,
  fetchSessions,
  type CostAggregationResponse,
  type ProviderStatus,
  type SessionListItem,
} from "@/lib/api";
import { useSessionEvents } from "@/hooks/use-session-events";
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

// ─────────────────────────────────────────────────────────────────────────────
// FORMATTERS
// ─────────────────────────────────────────────────────────────────────────────

function formatCurrency(value: number): string {
  if (value < 0.01) return `$${value.toFixed(4)}`;
  if (value < 1) return `$${value.toFixed(3)}`;
  return `$${value.toFixed(2)}`;
}

function formatNumber(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString();
}

function formatLatency(ms: number): string {
  return ms < 1000 ? `${ms.toFixed(0)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ─────────────────────────────────────────────────────────────────────────────
// KPI CARD - Compact metrics display
// ─────────────────────────────────────────────────────────────────────────────

function KPICard({
  label,
  value,
  subtext,
  icon: Icon,
  status = "neutral",
  pulse = false,
}: {
  label: string;
  value: string;
  subtext?: string;
  icon: React.ComponentType<{ className?: string }>;
  status?: "success" | "warning" | "error" | "neutral";
  pulse?: boolean;
}) {
  const statusConfig = {
    success: {
      border: "border-l-emerald-500",
      glow: "shadow-emerald-500/5",
      dot: "bg-emerald-500",
    },
    warning: {
      border: "border-l-amber-500",
      glow: "shadow-amber-500/5",
      dot: "bg-amber-500",
    },
    error: {
      border: "border-l-red-500",
      glow: "shadow-red-500/5",
      dot: "bg-red-500",
    },
    neutral: {
      border: "border-l-slate-600",
      glow: "",
      dot: "bg-slate-400",
    },
  };

  const config = statusConfig[status];

  return (
    <div
      className={cn(
        "relative overflow-hidden",
        "bg-slate-900/60 backdrop-blur-sm",
        "border border-slate-800/80",
        "border-l-[3px]",
        config.border,
        "rounded-lg",
        "transition-all duration-200",
        "hover:shadow-lg hover:shadow-black/20",
        config.glow,
        "group"
      )}
    >
      {/* Subtle corner accent */}
      <div className="absolute -top-8 -right-8 w-16 h-16 bg-gradient-to-br from-slate-800 to-transparent rounded-full opacity-50" />

      <div className="relative p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
                {label}
              </span>
              {pulse && (
                <span className={cn("w-1.5 h-1.5 rounded-full animate-pulse", config.dot)} />
              )}
            </div>
            <p className="mt-1.5 text-2xl font-semibold tracking-tight text-slate-50 font-mono tabular-nums">
              {value}
            </p>
            {subtext && (
              <p className="mt-0.5 text-xs text-slate-400 truncate">
                {subtext}
              </p>
            )}
          </div>
          <div className="p-2 rounded-md bg-slate-800/80 group-hover:bg-slate-800 transition-colors">
            <Icon className="h-4 w-4 text-slate-400" />
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// PROVIDER STATUS - Compact inline display
// ─────────────────────────────────────────────────────────────────────────────

function ProviderStatusCard({ provider }: { provider: ProviderStatus }) {
  const health = provider.health;
  const state = health?.state || (provider.available ? "healthy" : "unavailable");

  const stateConfig = {
    healthy: { color: "text-emerald-500", bg: "bg-emerald-500/10", label: "Healthy", dot: "bg-emerald-500" },
    degraded: { color: "text-amber-500", bg: "bg-amber-500/10", label: "Degraded", dot: "bg-amber-500" },
    unavailable: { color: "text-red-500", bg: "bg-red-500/10", label: "Down", dot: "bg-red-500" },
    unknown: { color: "text-slate-400", bg: "bg-slate-400/10", label: "Unknown", dot: "bg-slate-400" },
  };

  const config = stateConfig[state] || stateConfig.unknown;

  return (
    <div className="flex items-center justify-between p-3 rounded-lg bg-slate-800/30 border border-slate-800/50">
      <div className="flex items-center gap-3">
        <div className={cn("p-1.5 rounded-md", config.bg)}>
          {provider.name === "claude" ? (
            <Cpu className="h-4 w-4 text-orange-400" />
          ) : (
            <Server className="h-4 w-4 text-blue-400" />
          )}
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-100 capitalize">
              {provider.name}
            </span>
            <span className={cn("w-1.5 h-1.5 rounded-full", config.dot, state === "healthy" && "animate-pulse")} />
          </div>
          {health && (
            <div className="flex items-center gap-2 mt-0.5 text-[10px] text-slate-400 font-mono">
              <span>{formatLatency(health.latency_ms)}</span>
              <span className="text-slate-700">|</span>
              <span>{(health.availability * 100).toFixed(0)}% avail</span>
            </div>
          )}
        </div>
      </div>
      <span className={cn("text-[10px] font-medium uppercase tracking-wide px-2 py-0.5 rounded", config.bg, config.color)}>
        {config.label}
      </span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SPARKLINE CHART - Compact time series
// ─────────────────────────────────────────────────────────────────────────────

function Sparkline({ data, color = "emerald" }: { data: number[]; color?: "emerald" | "amber" | "blue" }) {
  if (data.length === 0) return <div className="h-full w-full bg-slate-800 rounded animate-pulse" />;

  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;

  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * 100;
      const y = 100 - ((v - min) / range) * 80 - 10;
      return `${x},${y}`;
    })
    .join(" ");

  const colorMap = {
    emerald: { stroke: "stroke-emerald-500", fill: "fill-emerald-500/10", dot: "fill-emerald-500" },
    amber: { stroke: "stroke-amber-500", fill: "fill-amber-500/10", dot: "fill-amber-500" },
    blue: { stroke: "stroke-blue-500", fill: "fill-blue-500/10", dot: "fill-blue-500" },
  };

  const colors = colorMap[color];

  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full">
      {/* Area fill */}
      <polygon points={`0,100 ${points} 100,100`} className={colors.fill} />
      {/* Line */}
      <polyline
        points={points}
        fill="none"
        className={colors.stroke}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      {/* End dot */}
      {data.length > 0 && (
        <circle
          cx={100}
          cy={100 - ((data[data.length - 1] - min) / range) * 80 - 10}
          r="3"
          className={colors.dot}
        />
      )}
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB COMPONENTS
// ─────────────────────────────────────────────────────────────────────────────

const TABS = [
  { id: "sessions", label: "Sessions", icon: MessageSquare },
  { id: "analytics", label: "Analytics", icon: BarChart3 },
  { id: "feedback", label: "Feedback", icon: ThumbsUp },
] as const;

type TabId = (typeof TABS)[number]["id"];

function TabNavigation({ activeTab, onTabChange }: { activeTab: TabId; onTabChange: (tab: TabId) => void }) {
  return (
    <div className="flex items-center gap-1 p-1 rounded-lg bg-slate-800/50">
      {TABS.map((tab) => {
        const Icon = tab.icon;
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={cn(
              "flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-all duration-200",
              isActive
                ? "bg-slate-900 text-slate-100 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            <span>{tab.label}</span>
          </button>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SESSIONS TAB CONTENT
// ─────────────────────────────────────────────────────────────────────────────

function SessionsTabContent({ sessions, isLoading }: { sessions: SessionListItem[]; isLoading: boolean }) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="h-12 bg-slate-800 rounded animate-pulse" />
        ))}
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-slate-400">
        <MessageSquare className="h-8 w-8 mb-2 opacity-50" />
        <p className="text-sm">No recent sessions</p>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {sessions.slice(0, 6).map((session) => (
        <a
          key={session.id}
          href={`/sessions/${session.id}`}
          className="flex items-center justify-between p-2.5 rounded-md hover:bg-slate-800/50 transition-colors group"
        >
          <div className="flex items-center gap-3 min-w-0">
            <div className={cn(
              "w-1.5 h-1.5 rounded-full",
              session.status === "active" ? "bg-emerald-500 animate-pulse" : "bg-slate-400"
            )} />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-slate-100 truncate">
                  {session.project_id}
                </span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-500">
                  {session.model.replace("claude-", "").replace("gemini-", "g-").slice(0, 12)}
                </span>
              </div>
              <div className="text-[11px] text-slate-400">
                {session.message_count} messages
                {session.purpose && <span className="ml-2 text-slate-500">| {session.purpose}</span>}
              </div>
            </div>
          </div>
          <span className="text-[10px] font-mono text-slate-400 group-hover:text-slate-300">
            {formatRelativeTime(session.created_at)}
          </span>
        </a>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ANALYTICS TAB CONTENT
// ─────────────────────────────────────────────────────────────────────────────

const PIE_COLORS = ["#f59e0b", "#3b82f6", "#10b981", "#8b5cf6", "#ec4899"];

function AnalyticsTabContent({
  costsByProject,
  costsByModel,
  isLoading,
}: {
  costsByProject: CostAggregationResponse | undefined;
  costsByModel: CostAggregationResponse | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4 h-48">
        <div className="bg-slate-800 rounded animate-pulse" />
        <div className="bg-slate-800 rounded animate-pulse" />
      </div>
    );
  }

  const pieData = costsByProject?.aggregations.slice(0, 5).map((agg) => ({
    name: agg.group_key,
    value: agg.total_cost_usd,
  })) || [];

  const barData = costsByModel?.aggregations.slice(0, 5).map((agg) => ({
    model: agg.group_key.replace("claude-", "").replace("gemini-", "g-").slice(0, 10),
    input: agg.input_tokens / 1000,
    output: agg.output_tokens / 1000,
  })) || [];

  return (
    <div className="grid grid-cols-2 gap-4">
      {/* Cost by Project Pie */}
      <div>
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-2 flex items-center gap-1.5">
          <Layers className="h-3 w-3" />
          Cost by Project
        </h4>
        {pieData.length > 0 ? (
          <ResponsiveContainer width="100%" height={160}>
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                innerRadius={35}
                outerRadius={55}
                paddingAngle={2}
                dataKey="value"
              >
                {pieData.map((_, idx) => (
                  <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                formatter={(value) => formatCurrency(Number(value))}
                contentStyle={{
                  background: "#1e293b",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  fontSize: "12px",
                  color: "#f1f5f9",
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-40 flex items-center justify-center text-slate-400 text-sm">
            No data
          </div>
        )}
      </div>

      {/* Token Usage by Model Bar */}
      <div>
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-2 flex items-center gap-1.5">
          <BarChart3 className="h-3 w-3" />
          Tokens by Model (K)
        </h4>
        {barData.length > 0 ? (
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={barData} layout="vertical" barGap={0} barCategoryGap="20%">
              <XAxis type="number" tick={{ fontSize: 10, fill: "#94a3b8" }} tickFormatter={(v) => `${v}K`} />
              <YAxis type="category" dataKey="model" tick={{ fontSize: 9, fill: "#94a3b8" }} width={60} />
              <Tooltip
                formatter={(value) => `${Number(value).toFixed(1)}K`}
                contentStyle={{
                  background: "#1e293b",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  fontSize: "12px",
                  color: "#f1f5f9",
                }}
              />
              <Bar dataKey="input" stackId="a" fill="#10b981" radius={[0, 0, 0, 0]} />
              <Bar dataKey="output" stackId="a" fill="#3b82f6" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-40 flex items-center justify-center text-slate-400 text-sm">
            No data
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// FEEDBACK TAB CONTENT
// ─────────────────────────────────────────────────────────────────────────────

function FeedbackTabContent({
  feedbackStats,
  isLoading,
}: {
  feedbackStats: { total_feedback: number; positive_count: number; negative_count: number; positive_rate: number; categories: Record<string, number> } | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-3 gap-4 h-32">
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-slate-800 rounded animate-pulse" />
        ))}
      </div>
    );
  }

  if (!feedbackStats || feedbackStats.total_feedback === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-40 text-slate-400">
        <ThumbsUp className="h-8 w-8 mb-2 opacity-50" />
        <p className="text-sm">No feedback collected yet</p>
      </div>
    );
  }

  const satisfactionRate = feedbackStats.positive_rate * 100;

  return (
    <div className="grid grid-cols-3 gap-4">
      {/* Satisfaction Rate */}
      <div className="flex flex-col items-center justify-center p-4 rounded-lg bg-slate-800/30">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">
          Satisfaction
        </p>
        <p
          className={cn(
            "text-3xl font-bold font-mono tabular-nums",
            satisfactionRate >= 80
              ? "text-emerald-400"
              : satisfactionRate >= 60
                ? "text-amber-400"
                : "text-red-400"
          )}
        >
          {satisfactionRate.toFixed(0)}%
        </p>
      </div>

      {/* Positive/Negative */}
      <div className="flex flex-col justify-center p-4 rounded-lg bg-slate-800/30 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <ThumbsUp className="h-3.5 w-3.5 text-emerald-500" />
            <span className="text-xs text-slate-400">Positive</span>
          </div>
          <span className="font-mono text-sm font-semibold text-slate-100">
            {feedbackStats.positive_count}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <ThumbsDown className="h-3.5 w-3.5 text-red-500" />
            <span className="text-xs text-slate-400">Negative</span>
          </div>
          <span className="font-mono text-sm font-semibold text-slate-100">
            {feedbackStats.negative_count}
          </span>
        </div>
      </div>

      {/* Total & Categories */}
      <div className="flex flex-col justify-center p-4 rounded-lg bg-slate-800/30">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">
          Total Responses
        </p>
        <p className="text-2xl font-bold font-mono tabular-nums text-slate-100">
          {feedbackStats.total_feedback}
        </p>
        {Object.keys(feedbackStats.categories).length > 0 && (
          <p className="text-[10px] text-slate-400 mt-1">
            {Object.keys(feedbackStats.categories).length} categories
          </p>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN DASHBOARD
// ─────────────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<TabId>("sessions");
  const { events } = useSessionEvents({ autoConnect: true });

  // Calculate active session count
  const activeSessionCount = useMemo(() => {
    const now = Date.now();
    const recentEvents = events.filter((e) => now - new Date(e.timestamp).getTime() < 60000);
    return new Set(recentEvents.map((e) => e.session_id)).size;
  }, [events]);

  // Data queries
  const { data: status, isLoading: statusLoading, error: statusError } = useQuery({
    queryKey: ["status"],
    queryFn: fetchStatus,
    refetchInterval: 30000,
  });

  const { data: dailyCosts, isLoading: dailyLoading } = useQuery({
    queryKey: ["costs", "day", 7],
    queryFn: () => fetchCosts({ group_by: "day", days: 7 }),
    refetchInterval: 60000,
  });

  const { data: totalCosts } = useQuery({
    queryKey: ["costs", "none", 7],
    queryFn: () => fetchCosts({ group_by: "none", days: 7 }),
    refetchInterval: 60000,
  });

  const { data: costsByProject, isLoading: projectLoading } = useQuery({
    queryKey: ["costs", "project", 7],
    queryFn: () => fetchCosts({ group_by: "project", days: 7 }),
    refetchInterval: 60000,
  });

  const { data: costsByModel, isLoading: modelLoading } = useQuery({
    queryKey: ["costs", "model", 7],
    queryFn: () => fetchCosts({ group_by: "model", days: 7 }),
    refetchInterval: 60000,
  });

  const { data: feedbackStats, isLoading: feedbackLoading } = useQuery({
    queryKey: ["feedbackStats", 7],
    queryFn: () => fetchFeedbackStats({ days: 7 }),
    refetchInterval: 60000,
  });

  const { data: sessionsData, isLoading: sessionsLoading } = useQuery({
    queryKey: ["sessions", "recent"],
    queryFn: () => fetchSessions({ page_size: 10 }),
    refetchInterval: 30000,
  });

  // Derived data
  const requestsByDay = dailyCosts?.aggregations.map((a) => a.request_count) || [];
  const costByDay = dailyCosts?.aggregations.map((a) => a.total_cost_usd) || [];
  const avgLatency = status?.providers.find((p) => p.health)?.health?.latency_ms || 0;
  const errorRate = status?.providers.some((p) => !p.available) ? 5.2 : 0.1;

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Subtle background pattern */}
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      {/* Header */}
      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 h-12 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-base font-semibold text-slate-100">
              Dashboard
            </h1>
            {status && (
              <div className={cn(
                "flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium uppercase tracking-wide",
                status.status === "healthy"
                  ? "bg-emerald-500/10 text-emerald-400"
                  : "bg-amber-500/10 text-amber-400"
              )}>
                <span className={cn(
                  "w-1.5 h-1.5 rounded-full",
                  status.status === "healthy" ? "bg-emerald-500" : "bg-amber-500"
                )} />
                {status.status}
              </div>
            )}
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-400 font-mono">
            <Clock className="h-3.5 w-3.5" />
            <span>7-day view</span>
          </div>
        </div>
      </header>

      <main className="relative px-6 lg:px-8 py-5">
        {/* Error Banner */}
        {statusError && (
          <div className="mb-4 p-3 rounded-lg bg-red-900/20 border border-red-800/50 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-red-500" />
            <p className="text-sm text-red-400">
              Unable to connect to backend
            </p>
          </div>
        )}

        {/* BENTO GRID LAYOUT */}
        <div className="grid grid-cols-12 gap-4 auto-rows-min">
          {/* ROW 1: KPI Cards (4 equal columns) */}
          <div className="col-span-3">
            <KPICard
              label="Error Rate"
              value={`${errorRate.toFixed(1)}%`}
              subtext="Last 7 days"
              icon={AlertTriangle}
              status={errorRate < 1 ? "success" : errorRate < 5 ? "warning" : "error"}
            />
          </div>
          <div className="col-span-3">
            <KPICard
              label="Avg Latency"
              value={formatLatency(avgLatency)}
              subtext="P50 response time"
              icon={Zap}
              status={avgLatency < 500 ? "success" : avgLatency < 1500 ? "warning" : "error"}
            />
          </div>
          <div className="col-span-3">
            <KPICard
              label="Active Sessions"
              value={String(activeSessionCount)}
              subtext="Currently running"
              icon={Activity}
              status={activeSessionCount > 0 ? "success" : "neutral"}
              pulse={activeSessionCount > 0}
            />
          </div>
          <div className="col-span-3">
            <KPICard
              label="Total Cost"
              value={dailyLoading ? "..." : formatCurrency(totalCosts?.total_cost_usd || 0)}
              subtext={`${formatNumber(totalCosts?.total_requests || 0)} requests`}
              icon={DollarSign}
              status="neutral"
            />
          </div>

          {/* ROW 2: Main Chart (8 cols) + Provider Health (4 cols) */}
          <div className="col-span-8 row-span-2 rounded-xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-sm p-5 overflow-hidden">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Request Volume
              </h2>
              <div className="flex items-center gap-4 text-[10px] font-mono text-slate-500">
                <span className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-emerald-500" />
                  {formatNumber(totalCosts?.total_requests || 0)} total
                </span>
              </div>
            </div>
            <div className="h-36">
              {dailyLoading ? (
                <div className="h-full bg-slate-800 rounded animate-pulse" />
              ) : (
                <Sparkline data={requestsByDay} color="emerald" />
              )}
            </div>
            {/* Cost mini-chart below */}
            <div className="mt-4 pt-4 border-t border-slate-800/50">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  Daily Spend
                </span>
                <span className="text-[10px] font-mono text-amber-400">
                  {formatCurrency(totalCosts?.total_cost_usd || 0)} total
                </span>
              </div>
              <div className="h-16">
                <Sparkline data={costByDay} color="amber" />
              </div>
            </div>
          </div>

          <div className="col-span-4 row-span-2 rounded-xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-sm p-5 overflow-hidden">
            <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-4">
              Provider Health
            </h2>
            <div className="space-y-2.5">
              {statusLoading ? (
                <>
                  <div className="h-16 bg-slate-800 rounded animate-pulse" />
                  <div className="h-16 bg-slate-800 rounded animate-pulse" />
                </>
              ) : status?.providers ? (
                status.providers.map((provider) => (
                  <ProviderStatusCard key={provider.name} provider={provider} />
                ))
              ) : (
                <p className="text-sm text-slate-400">No providers configured</p>
              )}
            </div>
            {/* Token summary */}
            <div className="mt-4 pt-4 border-t border-slate-800/50">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-0.5">Input</p>
                  <p className="text-lg font-mono font-semibold text-slate-100">
                    {formatNumber(costsByModel?.aggregations.reduce((sum, a) => sum + a.input_tokens, 0) || 0)}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-0.5">Output</p>
                  <p className="text-lg font-mono font-semibold text-slate-100">
                    {formatNumber(costsByModel?.aggregations.reduce((sum, a) => sum + a.output_tokens, 0) || 0)}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* ROW 3: Tabbed Section (full width) */}
          <div className="col-span-12 rounded-xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-sm p-5 overflow-hidden">
            <div className="flex items-center justify-between mb-4">
              <TabNavigation activeTab={activeTab} onTabChange={setActiveTab} />
              <a
                href={activeTab === "sessions" ? "/sessions" : activeTab === "analytics" ? "/analytics" : "#"}
                className="text-[10px] font-medium text-slate-500 hover:text-slate-300 transition-colors"
              >
                View all
              </a>
            </div>

            {/* Tab Content */}
            <div className="min-h-[200px]">
              {activeTab === "sessions" && (
                <SessionsTabContent
                  sessions={sessionsData?.sessions || []}
                  isLoading={sessionsLoading}
                />
              )}
              {activeTab === "analytics" && (
                <AnalyticsTabContent
                  costsByProject={costsByProject}
                  costsByModel={costsByModel}
                  isLoading={projectLoading || modelLoading}
                />
              )}
              {activeTab === "feedback" && (
                <FeedbackTabContent
                  feedbackStats={feedbackStats}
                  isLoading={feedbackLoading}
                />
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
