"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  DollarSign,
  Zap,
  Clock,
  AlertTriangle,
  Layers,
  MessageSquare,
  ChevronDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchStatus,
  fetchCosts,
  fetchSessions,
  fetchDashboardStats,
} from "@/lib/api";
import { useSessionEvents } from "@/hooks/use-session-events";
import { formatCurrency, formatNumber, formatLatency } from "@/lib/formatters";
import { KPICard } from "@/components/dashboard/KPICard";
import { ProviderStatusCard } from "@/components/dashboard/ProviderStatusCard";
import { Sparkline } from "@/components/dashboard/Sparkline";
import { TabNavigation, type TabId } from "@/components/dashboard/TabNavigation";
import { SessionsTabContent } from "@/components/dashboard/tabs/SessionsTabContent";
import { AnalyticsTabContent } from "@/components/dashboard/tabs/AnalyticsTabContent";
import { HealthTabContent } from "@/components/dashboard/tabs/HealthTabContent";

// ─────────────────────────────────────────────────────────────────────────────
// MAIN DASHBOARD
// ─────────────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<TabId>("sessions");
  const [daysRange, setDaysRange] = useState(7);
  const [showRangeDropdown, setShowRangeDropdown] = useState(false);
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
    queryKey: ["costs", "day", daysRange],
    queryFn: () => fetchCosts({ group_by: "day", days: daysRange }),
    refetchInterval: 60000,
  });

  const { data: totalCosts } = useQuery({
    queryKey: ["costs", "none", daysRange],
    queryFn: () => fetchCosts({ group_by: "none", days: daysRange }),
    refetchInterval: 60000,
  });

  const { data: costsByProject, isLoading: projectLoading } = useQuery({
    queryKey: ["costs", "project", daysRange],
    queryFn: () => fetchCosts({ group_by: "project", days: daysRange }),
    refetchInterval: 60000,
  });

  const { data: costsByModel, isLoading: modelLoading } = useQuery({
    queryKey: ["costs", "model", daysRange],
    queryFn: () => fetchCosts({ group_by: "model", days: daysRange }),
    refetchInterval: 60000,
  });

  const { data: sessionsData, isLoading: sessionsLoading } = useQuery({
    queryKey: ["sessions", "recent"],
    queryFn: () => fetchSessions({ page_size: 10 }),
    refetchInterval: 30000,
  });

  const { data: dashboardStats, isLoading: statsLoading } = useQuery({
    queryKey: ["dashboard-stats", daysRange],
    queryFn: () => fetchDashboardStats(daysRange),
    refetchInterval: 30000,
  });

  // Derived data
  const requestsByDay = dailyCosts?.aggregations.map((a) => a.request_count) || [];
  const costByDay = dailyCosts?.aggregations.map((a) => a.total_cost_usd) || [];

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
          <div className="relative">
            <button
              onClick={() => setShowRangeDropdown(!showRangeDropdown)}
              className="flex items-center gap-2 px-2 py-1 rounded-md text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 transition-colors font-mono"
            >
              <Clock className="h-3.5 w-3.5" />
              <span>{daysRange}-day view</span>
              <ChevronDown className="h-3 w-3" />
            </button>
            {showRangeDropdown && (
              <div className="absolute right-0 top-full mt-1 py-1 w-28 rounded-lg bg-slate-800 border border-slate-700 shadow-xl z-30">
                {[1, 7, 14, 30].map((days) => (
                  <button
                    key={days}
                    onClick={() => {
                      setDaysRange(days);
                      setShowRangeDropdown(false);
                    }}
                    className={cn(
                      "w-full px-3 py-1.5 text-left text-xs font-mono",
                      days === daysRange
                        ? "text-emerald-400 bg-emerald-500/10"
                        : "text-slate-300 hover:bg-slate-700"
                    )}
                  >
                    {days === 1 ? "Today" : `${days} days`}
                  </button>
                ))}
              </div>
            )}
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
          {/* ROW 1: KPI Cards (Full width) */}
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
              {activeTab === "sessions" && (
                <a
                  href="/sessions"
                  className="text-[10px] font-medium text-slate-500 hover:text-slate-300 transition-colors"
                >
                  View all
                </a>
              )}
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
              {activeTab === "health" && (
                <HealthTabContent
                  stats={dashboardStats}
                  status={status}
                />
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
