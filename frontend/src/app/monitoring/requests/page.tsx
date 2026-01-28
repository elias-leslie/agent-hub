"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Clock,
  Filter,
  RefreshCw,
  Zap,
  Server,
  Terminal,
  Code2,
  TrendingUp,
  AlertCircle,
  CheckCircle2,
  Bot,
  ArrowUpRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { buildApiUrl, fetchApi } from "@/lib/api-config";

// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

interface RequestLogEntry {
  id: number;
  client_id: string | null;
  client_display_name: string | null;
  request_source: string | null;
  endpoint: string;
  method: string;
  status_code: number;
  rejection_reason: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  latency_ms: number | null;
  model: string | null;
  agent_slug: string | null;
  tool_type: string | null;
  tool_name: string | null;
  source_path: string | null;
  created_at: string;
}

interface RequestLogResponse {
  requests: RequestLogEntry[];
  total: number;
}

interface MetricsSummary {
  total_requests: number;
  success_rate: number;
  avg_latency_ms: number;
}

interface ToolTypeBreakdown {
  tool_type: string;
  count: number;
}

interface EndpointMetric {
  endpoint: string;
  count: number;
  success_rate: number;
  avg_latency_ms: number;
}

interface ToolNameMetric {
  tool_name: string;
  count: number;
  avg_latency_ms: number;
  success_rate: number;
}

interface MetricsResponse {
  summary: MetricsSummary;
  by_tool_type: ToolTypeBreakdown[];
  by_tool_name: ToolNameMetric[];
  by_endpoint: EndpointMetric[];
}

// ─────────────────────────────────────────────────────────────────────────────
// API FUNCTIONS
// ─────────────────────────────────────────────────────────────────────────────

async function fetchRequestLog(params: {
  client_id?: string;
  status_code?: number;
  rejected_only?: boolean;
  tool_type?: string;
  agent_slug?: string;
  limit?: number;
  offset?: number;
}): Promise<RequestLogResponse> {
  const searchParams = new URLSearchParams();
  if (params.client_id) searchParams.set("client_id", params.client_id);
  if (params.status_code) searchParams.set("status_code", params.status_code.toString());
  if (params.rejected_only) searchParams.set("rejected_only", "true");
  if (params.tool_type) searchParams.set("tool_type", params.tool_type);
  if (params.agent_slug) searchParams.set("agent_slug", params.agent_slug);
  if (params.limit) searchParams.set("limit", params.limit.toString());
  if (params.offset) searchParams.set("offset", params.offset.toString());

  const response = await fetchApi(buildApiUrl(`/api/access-control/request-log?${searchParams.toString()}`));
  if (!response.ok) {
    throw new Error(`Failed to fetch request log: ${response.statusText}`);
  }
  return response.json();
}

async function fetchMetrics(hours: number = 24): Promise<MetricsResponse> {
  const response = await fetchApi(buildApiUrl(`/api/access-control/metrics?hours=${hours}&limit=10`));
  if (!response.ok) {
    throw new Error(`Failed to fetch metrics: ${response.statusText}`);
  }
  return response.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// FORMATTERS
// ─────────────────────────────────────────────────────────────────────────────

function formatTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;

  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatLatency(ms: number | null): string {
  if (ms === null) return "-";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPONENTS
// ─────────────────────────────────────────────────────────────────────────────

function MetricCard({
  label,
  value,
  subtext,
  icon: Icon,
  trend,
  status = "neutral",
}: {
  label: string;
  value: string;
  subtext?: string;
  icon: React.ComponentType<{ className?: string }>;
  trend?: "up" | "down" | "flat";
  status?: "success" | "warning" | "error" | "neutral";
}) {
  const statusColors = {
    success: "border-l-emerald-500 shadow-emerald-500/5",
    warning: "border-l-amber-500 shadow-amber-500/5",
    error: "border-l-red-500 shadow-red-500/5",
    neutral: "border-l-slate-600",
  };

  return (
    <div
      className={cn(
        "relative overflow-hidden",
        "bg-slate-900/60 backdrop-blur-sm",
        "border border-slate-800/80 border-l-[3px]",
        statusColors[status],
        "rounded-lg p-4",
        "transition-all duration-200 hover:shadow-lg hover:shadow-black/20",
        "group"
      )}
    >
      <div className="absolute -top-8 -right-8 w-16 h-16 bg-gradient-to-br from-slate-800 to-transparent rounded-full opacity-50" />

      <div className="relative flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
              {label}
            </span>
            {trend && (
              <TrendingUp
                className={cn(
                  "h-3 w-3",
                  trend === "up" && "text-emerald-500",
                  trend === "down" && "text-red-500 rotate-180",
                  trend === "flat" && "text-slate-500 rotate-90"
                )}
              />
            )}
          </div>
          <p className="mt-1.5 text-2xl font-semibold tracking-tight text-slate-50 font-mono tabular-nums">
            {value}
          </p>
          {subtext && (
            <p className="mt-0.5 text-xs text-slate-400 truncate">{subtext}</p>
          )}
        </div>
        <div className="p-2 rounded-md bg-slate-800/80 group-hover:bg-slate-800 transition-colors">
          <Icon className="h-4 w-4 text-slate-400" />
        </div>
      </div>
    </div>
  );
}

function ToolTypeBadge({ type }: { type: string | null }) {
  const config = {
    api: { icon: Server, color: "text-blue-400", bg: "bg-blue-500/10" },
    cli: { icon: Terminal, color: "text-emerald-400", bg: "bg-emerald-500/10" },
    sdk: { icon: Code2, color: "text-purple-400", bg: "bg-purple-500/10" },
  };

  const typeKey = (type?.toLowerCase() || "api") as keyof typeof config;
  const { icon: Icon, color, bg } = config[typeKey] || config.api;

  return (
    <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium", bg, color)}>
      <Icon className="h-3 w-3" />
      {type?.toUpperCase() || "API"}
    </span>
  );
}

function StatusBadge({ code }: { code: number }) {
  const config = code >= 500
    ? { icon: AlertCircle, color: "text-red-400", bg: "bg-red-500/10" }
    : code >= 400
    ? { icon: AlertCircle, color: "text-amber-400", bg: "bg-amber-500/10" }
    : { icon: CheckCircle2, color: "text-emerald-400", bg: "bg-emerald-500/10" };

  return (
    <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono", config.bg, config.color)}>
      <config.icon className="h-3 w-3" />
      {code}
    </span>
  );
}

function ToolTypeDistribution({ data }: { data: ToolTypeBreakdown[] }) {
  const total = data.reduce((sum, d) => sum + d.count, 0);
  if (total === 0) return null;

  const colors = {
    api: "bg-blue-500",
    cli: "bg-emerald-500",
    sdk: "bg-purple-500",
  };

  return (
    <div className="space-y-3">
      {/* Bar visualization */}
      <div className="h-2 rounded-full bg-slate-800 overflow-hidden flex">
        {data.map((item) => {
          const pct = (item.count / total) * 100;
          const colorKey = item.tool_type?.toLowerCase() as keyof typeof colors;
          return (
            <div
              key={item.tool_type}
              className={cn("h-full transition-all duration-500", colors[colorKey] || "bg-slate-600")}
              style={{ width: `${pct}%` }}
            />
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4">
        {data.map((item) => {
          const pct = ((item.count / total) * 100).toFixed(0);
          const colorKey = item.tool_type?.toLowerCase() as keyof typeof colors;
          return (
            <div key={item.tool_type} className="flex items-center gap-2">
              <span className={cn("w-2 h-2 rounded-full", colors[colorKey] || "bg-slate-600")} />
              <span className="text-xs text-slate-400">
                {item.tool_type?.toUpperCase() || "API"}: {formatNumber(item.count)} ({pct}%)
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TopEndpoints({ data }: { data: EndpointMetric[] }) {
  if (data.length === 0) return null;

  return (
    <div className="space-y-2">
      {data.slice(0, 5).map((endpoint, idx) => (
        <div
          key={endpoint.endpoint}
          className="flex items-center gap-3 p-2 rounded-lg bg-slate-800/30 hover:bg-slate-800/50 transition-colors"
        >
          <span className="text-xs font-mono text-slate-500 w-4">{idx + 1}</span>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-mono text-slate-200 truncate">{endpoint.endpoint}</p>
            <div className="flex items-center gap-3 mt-0.5 text-[10px] text-slate-500">
              <span>{formatNumber(endpoint.count)} reqs</span>
              <span className={cn(
                endpoint.success_rate >= 95 ? "text-emerald-400" :
                endpoint.success_rate >= 80 ? "text-amber-400" : "text-red-400"
              )}>
                {endpoint.success_rate.toFixed(0)}% success
              </span>
              <span>{formatLatency(endpoint.avg_latency_ms)}</span>
            </div>
          </div>
          <ArrowUpRight className="h-3 w-3 text-slate-600" />
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN PAGE
// ─────────────────────────────────────────────────────────────────────────────

export default function MonitoringRequestsPage() {
  // Filters
  const [clientFilter, setClientFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<number | undefined>();
  const [toolTypeFilter, setToolTypeFilter] = useState<string | undefined>();
  const [agentFilter, setAgentFilter] = useState("");
  const [rejectedOnly, setRejectedOnly] = useState(false);
  const [page, setPage] = useState(0);
  const [timeRange, setTimeRange] = useState(24);
  const pageSize = 50;

  // Queries
  const { data: metrics, isLoading: metricsLoading } = useQuery({
    queryKey: ["monitoring-metrics", timeRange],
    queryFn: () => fetchMetrics(timeRange),
    refetchInterval: 30000,
  });

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["request-log", clientFilter, statusFilter, toolTypeFilter, agentFilter, rejectedOnly, page],
    queryFn: () => fetchRequestLog({
      client_id: clientFilter || undefined,
      status_code: statusFilter,
      tool_type: toolTypeFilter,
      agent_slug: agentFilter || undefined,
      rejected_only: rejectedOnly,
      limit: pageSize,
      offset: page * pageSize,
    }),
    refetchInterval: 10000,
  });

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
            {data && (
              <span className="text-xs text-slate-500">({formatNumber(data.total)} total)</span>
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
            value={metricsLoading ? "..." : formatLatency(metrics?.summary.avg_latency_ms || 0)}
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

        {/* Distribution & Top Endpoints */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
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
        <div className="flex flex-wrap gap-3">
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700">
            <Filter className="h-4 w-4 text-slate-400" />
            <input
              type="text"
              placeholder="Filter by client ID..."
              value={clientFilter}
              onChange={(e) => { setClientFilter(e.target.value); setPage(0); }}
              className="bg-transparent border-none outline-none text-sm text-slate-100 placeholder-slate-500 w-36"
            />
          </div>

          <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700">
            <Bot className="h-4 w-4 text-slate-400" />
            <input
              type="text"
              placeholder="Filter by agent..."
              value={agentFilter}
              onChange={(e) => { setAgentFilter(e.target.value); setPage(0); }}
              className="bg-transparent border-none outline-none text-sm text-slate-100 placeholder-slate-500 w-32"
            />
          </div>

          <select
            value={toolTypeFilter || ""}
            onChange={(e) => { setToolTypeFilter(e.target.value || undefined); setPage(0); }}
            className="px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700 text-sm text-slate-100"
          >
            <option value="">All Tool Types</option>
            <option value="api">API</option>
            <option value="cli">CLI</option>
            <option value="sdk">SDK</option>
          </select>

          <select
            value={statusFilter || ""}
            onChange={(e) => { setStatusFilter(e.target.value ? parseInt(e.target.value) : undefined); setPage(0); }}
            className="px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700 text-sm text-slate-100"
          >
            <option value="">All Status Codes</option>
            <option value="200">200 OK</option>
            <option value="400">400 Bad Request</option>
            <option value="403">403 Forbidden</option>
            <option value="500">500 Error</option>
          </select>

          <label className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700 cursor-pointer">
            <input
              type="checkbox"
              checked={rejectedOnly}
              onChange={(e) => { setRejectedOnly(e.target.checked); setPage(0); }}
              className="rounded bg-slate-700 border-slate-600 text-amber-500 focus:ring-amber-500/50"
            />
            <span className="text-sm text-slate-300">Rejected only</span>
          </label>
        </div>

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
        ) : data?.requests.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-400">
            <Clock className="h-12 w-12 mb-4 opacity-50" />
            <p className="text-lg">No requests found</p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto rounded-xl border border-slate-800/80">
              <table className="w-full min-w-[1200px]">
                <thead className="bg-slate-800/50">
                  <tr>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      Time
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      Type
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      Tool
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      Agent
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      Client
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      Endpoint
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      Status
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      Latency
                    </th>
                    <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      Reason
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {data?.requests.map((req) => (
                    <tr key={req.id} className="hover:bg-slate-800/30 transition-colors">
                      <td className="px-4 py-3 text-xs text-slate-400 font-mono whitespace-nowrap">
                        {formatTime(req.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <ToolTypeBadge type={req.tool_type} />
                      </td>
                      <td className="px-4 py-3">
                        {req.tool_name ? (
                          <span className="text-sm font-mono text-slate-300">
                            {req.tool_name}
                          </span>
                        ) : (
                          <span className="text-sm text-slate-500">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {req.agent_slug ? (
                          <span className="inline-flex items-center gap-1.5 text-sm text-amber-400 font-medium">
                            <Bot className="h-3.5 w-3.5" />
                            {req.agent_slug}
                          </span>
                        ) : (
                          <span className="text-sm text-slate-500">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div>
                          <p className="text-sm text-slate-100">
                            {req.client_display_name || "Unknown"}
                          </p>
                          {req.request_source && (
                            <p className="text-xs text-slate-500">{req.request_source}</p>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs font-mono text-slate-500 mr-2">{req.method}</span>
                        <span className="text-sm text-slate-100 font-mono">{req.endpoint}</span>
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge code={req.status_code} />
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-400 font-mono">
                        {formatLatency(req.latency_ms)}
                      </td>
                      <td className="px-4 py-3 text-sm text-amber-400 max-w-xs truncate">
                        {req.rejection_reason || "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {data && data.total > pageSize && (
              <div className="flex items-center justify-between">
                <p className="text-sm text-slate-400">
                  Showing {page * pageSize + 1}-{Math.min((page + 1) * pageSize, data.total)} of {formatNumber(data.total)}
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setPage(Math.max(0, page - 1))}
                    disabled={page === 0}
                    className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Previous
                  </button>
                  <button
                    onClick={() => setPage(page + 1)}
                    disabled={(page + 1) * pageSize >= data.total}
                    className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
