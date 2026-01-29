"use client";

import { useState, useMemo, useCallback } from "react";
import { useQuery, useInfiniteQuery } from "@tanstack/react-query";
import {
  Activity,
  Clock,
  RefreshCw,
  Zap,
  CheckCircle2,
  Terminal,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchRequestLog, fetchMetrics } from "./api";
import { SortField, SortDirection } from "./types";
import { formatNumber } from "./utils";
import { MetricCard } from "./components/MetricCard";
import { ToolTypeDistribution } from "./components/ToolTypeDistribution";
import { TopTools } from "./components/TopTools";
import { TopEndpoints } from "./components/TopEndpoints";
import { Filters } from "./components/Filters";
import { RequestTable } from "./components/RequestTable";

export default function MonitoringRequestsPage() {
  // Filters
  const [clientFilter, setClientFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<number | undefined>();
  const [toolTypeFilter, setToolTypeFilter] = useState<string | undefined>();
  const [agentFilter, setAgentFilter] = useState("");
  const [rejectedOnly, setRejectedOnly] = useState(false);
  const [timeRange, setTimeRange] = useState(24);
  const [sortField, setSortField] = useState<SortField>("time");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const pageSize = 50;

  // Sort handler
  const handleSort = useCallback((field: SortField) => {
    if (sortField === field) {
      setSortDirection(d => d === "desc" ? "asc" : "desc");
    } else {
      setSortField(field);
      setSortDirection("desc");
    }
  }, [sortField]);

  // Queries
  const { data: metrics, isLoading: metricsLoading } = useQuery({
    queryKey: ["monitoring-metrics", timeRange],
    queryFn: () => fetchMetrics(timeRange),
    refetchInterval: 30000,
  });

  const {
    data,
    isLoading,
    error,
    refetch,
    isFetching,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["request-log", clientFilter, statusFilter, toolTypeFilter, agentFilter, rejectedOnly],
    queryFn: ({ pageParam = 0 }) => fetchRequestLog({
      client_id: clientFilter || undefined,
      status_code: statusFilter,
      tool_type: toolTypeFilter,
      agent_slug: agentFilter || undefined,
      rejected_only: rejectedOnly,
      limit: pageSize,
      offset: pageParam * pageSize,
    }),
    getNextPageParam: (lastPage, allPages) => {
      const totalLoaded = allPages.length * pageSize;
      return totalLoaded < lastPage.total ? allPages.length : undefined;
    },
    initialPageParam: 0,
    refetchInterval: 10000,
  });

  // Flatten and sort requests
  const requests = useMemo(() => {
    const flat = data?.pages.flatMap((page) => page.requests) ?? [];

    return [...flat].sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "time":
          cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
          break;
        case "type":
          cmp = (a.tool_type || "").localeCompare(b.tool_type || "");
          break;
        case "tool":
          cmp = (a.tool_name || "").localeCompare(b.tool_name || "");
          break;
        case "agent":
          cmp = (a.agent_slug || "").localeCompare(b.agent_slug || "");
          break;
        case "status":
          cmp = a.status_code - b.status_code;
          break;
        case "latency":
          cmp = (a.latency_ms || 0) - (b.latency_ms || 0);
          break;
      }
      return sortDirection === "asc" ? cmp : -cmp;
    });
  }, [data, sortField, sortDirection]);
  const total = data?.pages[0]?.total ?? 0;

  // Derived metrics
  const successStatus = useMemo(() => {
    if (!metrics?.summary) return "neutral" as const;
    const rate = metrics.summary.success_rate;
    if (rate >= 95) return "success" as const;
    if (rate >= 80) return "warning" as const;
    return "error" as const;
  }, [metrics]);

  const latencyStatus = useMemo(() => {
    if (!metrics?.summary) return "neutral" as const;
    const ms = metrics.summary.avg_latency_ms;
    if (ms < 500) return "success" as const;
    if (ms < 2000) return "warning" as const;
    return "error" as const;
  }, [metrics]);

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      {/* Header */}
      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 h-12 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Activity className="h-5 w-5 text-amber-500" />
            <h1 className="text-base font-semibold text-slate-100">Request Monitoring</h1>
            {total > 0 && (
              <span className="text-xs text-slate-500">({formatNumber(total)} total)</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <select
              value={timeRange}
              onChange={(e) => setTimeRange(parseInt(e.target.value))}
              className="px-2 py-1 text-xs rounded bg-slate-800 border border-slate-700 text-slate-300"
            >
              <option value={1}>Last 1h</option>
              <option value={6}>Last 6h</option>
              <option value={24}>Last 24h</option>
              <option value={72}>Last 3d</option>
              <option value={168}>Last 7d</option>
            </select>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm transition-colors"
            >
              <RefreshCw className={cn("h-4 w-4", isFetching && "animate-spin")} />
              Refresh
            </button>
          </div>
        </div>
      </header>

      <main className="relative px-6 lg:px-8 py-6 space-y-6">
        {/* Metrics Summary Row */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <MetricCard
            label="Total Requests"
            value={metricsLoading ? "..." : formatNumber(metrics?.summary.total_requests || 0)}
            subtext={`Last ${timeRange}h`}
            icon={Activity}
            status="neutral"
          />
          <MetricCard
            label="Success Rate"
            value={metricsLoading ? "..." : `${(metrics?.summary.success_rate || 0).toFixed(1)}%`}
            subtext="2xx/3xx responses"
            icon={CheckCircle2}
            status={successStatus}
          />
          <MetricCard
            label="Avg Latency"
            value={metricsLoading ? "..." : `${metrics?.summary.avg_latency_ms || 0}ms`}
            subtext="P50 response time"
            icon={Zap}
            status={latencyStatus}
          />
          <MetricCard
            label="Tool Types"
            value={metricsLoading ? "..." : String(metrics?.by_tool_type.length || 0)}
            subtext="API, CLI, SDK"
            icon={Terminal}
            status="neutral"
          />
        </div>

        {/* Distribution & Top Sections */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Tool Type Distribution */}
          <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-sm p-5">
            <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-4">
              Request Distribution by Tool Type
            </h2>
            {metricsLoading ? (
              <div className="h-16 bg-slate-800 rounded animate-pulse" />
            ) : (
              <ToolTypeDistribution data={metrics?.by_tool_type || []} />
            )}
          </div>

          {/* Top Tools */}
          <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-sm p-5">
            <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-4">
              Top Tools (CLI/SDK)
            </h2>
            {metricsLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-12 bg-slate-800 rounded animate-pulse" />
                ))}
              </div>
            ) : (
              <TopTools data={metrics?.by_tool_name || []} />
            )}
          </div>

          {/* Top Endpoints */}
          <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-sm p-5">
            <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-4">
              Top Endpoints
            </h2>
            {metricsLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-12 bg-slate-800 rounded animate-pulse" />
                ))}
              </div>
            ) : (
              <TopEndpoints data={metrics?.by_endpoint || []} />
            )}
          </div>
        </div>

        {/* Filters */}
        <Filters
          clientFilter={clientFilter}
          setClientFilter={setClientFilter}
          agentFilter={agentFilter}
          setAgentFilter={setAgentFilter}
          toolTypeFilter={toolTypeFilter}
          setToolTypeFilter={setToolTypeFilter}
          statusFilter={statusFilter}
          setStatusFilter={setStatusFilter}
          rejectedOnly={rejectedOnly}
          setRejectedOnly={setRejectedOnly}
        />

        {/* Error State */}
        {error && (
          <div className="p-3 rounded-lg bg-red-900/20 border border-red-800/50">
            <p className="text-sm text-red-400">Failed to load request log</p>
          </div>
        )}

        {/* Table */}
        {isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-14 bg-slate-800 rounded animate-pulse" />
            ))}
          </div>
        ) : requests.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-400">
            <Clock className="h-12 w-12 mb-4 opacity-50" />
            <p className="text-lg">No requests found</p>
          </div>
        ) : (
          <RequestTable
            requests={requests}
            total={total}
            sortField={sortField}
            sortDirection={sortDirection}
            onSort={handleSort}
            isFetchingNextPage={isFetchingNextPage}
            hasNextPage={hasNextPage}
            onFetchNextPage={fetchNextPage}
          />
        )}
      </main>
    </div>
  );
}
