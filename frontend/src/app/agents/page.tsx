"use client";

import { useState, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  RefreshCw,
  Search,
  AlertCircle,
  MoreVertical,
  Play,
  Copy,
  Archive,
  Plus,
  Activity,
  Clock,
  CheckCircle2,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchApi } from "@/lib/api-config";
import { GlobalInstructionsPanel } from "@/components/GlobalInstructionsPanel";

// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

interface Agent {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  primary_model_id: string;
  fallback_models: string[];
  temperature: number;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

interface AgentListResponse {
  agents: Agent[];
  total: number;
}

interface AgentMetrics {
  slug: string;
  requests_24h: number;
  avg_latency_ms: number;
  success_rate: number;
  tokens_24h: number;
  cost_24h_usd: number;
  latency_trend: number[];
  success_trend: number[];
}

interface AgentMetricsResponse {
  metrics: Record<string, AgentMetrics>;
}

// Sort types
type SortField = "name" | "model" | "status" | "requests" | "latency" | "success" | "version";
type SortDirection = "asc" | "desc";

// ─────────────────────────────────────────────────────────────────────────────
// API
// ─────────────────────────────────────────────────────────────────────────────

async function fetchAgents(activeOnly = true): Promise<AgentListResponse> {
  const params = new URLSearchParams();
  params.set("active_only", String(activeOnly));

  const res = await fetchApi(`/api/agents?${params}`);
  if (!res.ok) {
    throw new Error("Failed to fetch agents");
  }
  return res.json();
}

async function fetchMetrics(): Promise<AgentMetricsResponse> {
  const res = await fetchApi("/api/agents/metrics/all");
  if (!res.ok) {
    // Return empty metrics on error - don't fail the whole page
    return { metrics: {} };
  }
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPONENTS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Sparkline chart component for displaying trend data.
 * Uses SVG for crisp rendering at small sizes.
 */
function Sparkline({
  data,
  color = "emerald",
  width = 60,
  height = 20,
}: {
  data: number[];
  color?: "emerald" | "blue" | "amber" | "red";
  width?: number;
  height?: number;
}) {
  if (!data || data.length < 2) {
    return (
      <div
        className="flex items-center justify-center text-[9px] text-slate-400"
        style={{ width, height }}
      >
        No data
      </div>
    );
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const padding = 2;
  const effectiveWidth = width - padding * 2;
  const effectiveHeight = height - padding * 2;

  const points = data.map((value, index) => {
    const x = padding + (index / (data.length - 1)) * effectiveWidth;
    const y = padding + effectiveHeight - ((value - min) / range) * effectiveHeight;
    return `${x},${y}`;
  });

  const colorMap = {
    emerald: { stroke: "#10b981", fill: "#10b98120" },
    blue: { stroke: "#3b82f6", fill: "#3b82f620" },
    amber: { stroke: "#f59e0b", fill: "#f59e0b20" },
    red: { stroke: "#ef4444", fill: "#ef444420" },
  };

  const colors = colorMap[color];

  // Create fill polygon (line + bottom edge)
  const fillPoints = [
    `${padding},${height - padding}`,
    ...points,
    `${width - padding},${height - padding}`,
  ].join(" ");

  return (
    <svg width={width} height={height} className="flex-shrink-0">
      <polygon points={fillPoints} fill={colors.fill} />
      <polyline
        points={points.join(" ")}
        fill="none"
        stroke={colors.stroke}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * Metrics cell displaying value + sparkline
 */
function MetricCell({
  label,
  value,
  unit,
  trend,
  color = "emerald",
}: {
  label: string;
  value: string | number;
  unit?: string;
  trend?: number[];
  color?: "emerald" | "blue" | "amber" | "red";
}) {
  return (
    <div className="flex items-center gap-2">
      <div className="min-w-[50px]">
        <span className="text-xs font-semibold tabular-nums text-slate-700 dark:text-slate-300">
          {value}
        </span>
        {unit && (
          <span className="text-[10px] text-slate-400 ml-0.5">{unit}</span>
        )}
      </div>
      {trend && trend.length > 0 && <Sparkline data={trend} color={color} />}
    </div>
  );
}

function ModelPill({ model }: { model: string }) {
  const isClaude = model.toLowerCase().includes("claude");
  const shortName = model
    .replace("claude-", "")
    .replace("gemini-", "")
    .replace("-20250514", "")
    .slice(0, 12);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide border",
        isClaude
          ? "border-purple-400/60 text-purple-600 dark:text-purple-400 bg-purple-50/80 dark:bg-purple-950/40"
          : "border-emerald-400/60 text-emerald-600 dark:text-emerald-400 bg-emerald-50/80 dark:bg-emerald-950/40"
      )}
    >
      <span
        className={cn(
          "w-1.5 h-1.5 rounded-full",
          isClaude ? "bg-purple-500" : "bg-emerald-500"
        )}
      />
      {shortName}
    </span>
  );
}

function StatusBadge({ isActive }: { isActive: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide",
        isActive
          ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400"
          : "bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400"
      )}
    >
      <span
        className={cn(
          "w-1.5 h-1.5 rounded-full",
          isActive ? "bg-emerald-500" : "bg-slate-400"
        )}
      />
      {isActive ? "Active" : "Inactive"}
    </span>
  );
}

function SortableHeader({
  label,
  field,
  currentField,
  direction,
  onSort,
  icon,
  align = "left",
}: {
  label: string;
  field: SortField;
  currentField: SortField;
  direction: SortDirection;
  onSort: (field: SortField) => void;
  icon?: React.ReactNode;
  align?: "left" | "right";
}) {
  const isActive = currentField === field;

  return (
    <button
      onClick={() => onSort(field)}
      className={cn(
        "flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider transition-colors",
        "text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300",
        isActive && "text-slate-700 dark:text-slate-200",
        align === "right" && "justify-end ml-auto"
      )}
    >
      {icon}
      {label}
      {isActive ? (
        direction === "asc" ? (
          <ArrowUp className="h-3 w-3" />
        ) : (
          <ArrowDown className="h-3 w-3" />
        )
      ) : (
        <ArrowUpDown className="h-3 w-3 opacity-30" />
      )}
    </button>
  );
}

function AgentActionsMenu({
  agent,
  onClone,
  onArchive,
}: {
  agent: Agent;
  onClone?: (agent: Agent) => void;
  onArchive?: (agent: Agent) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
      >
        <MoreVertical className="h-4 w-4 text-slate-400" />
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 top-8 z-50 w-40 py-1 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 shadow-lg">
            <button
              onClick={() => {
                window.location.href = `/agents/${agent.slug}/playground`;
                setOpen(false);
              }}
              className="flex items-center gap-2 w-full px-3 py-2 text-xs text-left hover:bg-slate-50 dark:hover:bg-slate-700"
            >
              <Play className="h-3.5 w-3.5" />
              Playground
            </button>
            <button
              onClick={() => {
                onClone?.(agent);
                setOpen(false);
              }}
              className="flex items-center gap-2 w-full px-3 py-2 text-xs text-left hover:bg-slate-50 dark:hover:bg-slate-700"
            >
              <Copy className="h-3.5 w-3.5" />
              Clone
            </button>
            <div className="border-t border-slate-100 dark:border-slate-700 my-1" />
            <button
              onClick={() => {
                onArchive?.(agent);
                setOpen(false);
              }}
              className="flex items-center gap-2 w-full px-3 py-2 text-xs text-left text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20"
            >
              <Archive className="h-3.5 w-3.5" />
              Archive
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN PAGE
// ─────────────────────────────────────────────────────────────────────────────

export default function AgentsPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [sortField, setSortField] = useState<SortField>("name");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");

  const handleSort = useCallback((field: SortField) => {
    if (sortField === field) {
      setSortDirection(d => d === "desc" ? "asc" : "desc");
    } else {
      setSortField(field);
      setSortDirection("desc");
    }
  }, [sortField]);

  const { data, isLoading, error, refetch, isRefetching } = useQuery({
    queryKey: ["agents", { activeOnly: !showInactive }],
    queryFn: () => fetchAgents(!showInactive),
  });

  const { data: metricsData } = useQuery({
    queryKey: ["agent-metrics"],
    queryFn: fetchMetrics,
    refetchInterval: 60000, // Refresh metrics every minute
  });

  const filteredAgents = useMemo(() => {
    if (!data?.agents) return [];

    let agents = data.agents;

    // Filter by search
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      agents = agents.filter(
        (a) =>
          a.slug.toLowerCase().includes(query) ||
          a.name.toLowerCase().includes(query) ||
          a.description?.toLowerCase().includes(query)
      );
    }

    // Sort
    return [...agents].sort((a, b) => {
      let cmp = 0;
      const metricsA = metricsData?.metrics?.[a.slug];
      const metricsB = metricsData?.metrics?.[b.slug];

      switch (sortField) {
        case "name":
          cmp = a.name.localeCompare(b.name);
          break;
        case "model":
          cmp = a.primary_model_id.localeCompare(b.primary_model_id);
          break;
        case "status":
          cmp = (a.is_active ? 1 : 0) - (b.is_active ? 1 : 0);
          break;
        case "requests":
          cmp = (metricsA?.requests_24h ?? 0) - (metricsB?.requests_24h ?? 0);
          break;
        case "latency":
          cmp = (metricsA?.avg_latency_ms ?? 0) - (metricsB?.avg_latency_ms ?? 0);
          break;
        case "success":
          cmp = (metricsA?.success_rate ?? 100) - (metricsB?.success_rate ?? 100);
          break;
        case "version":
          cmp = a.version - b.version;
          break;
      }
      return sortDirection === "asc" ? cmp : -cmp;
    });
  }, [data?.agents, searchQuery, sortField, sortDirection, metricsData]);

  const getMetrics = useCallback(
    (slug: string): AgentMetrics | null => {
      return metricsData?.metrics?.[slug] ?? null;
    },
    [metricsData]
  );

  const handleClone = useCallback((agent: Agent) => {
    // Navigate to create page with agent data pre-filled
    const params = new URLSearchParams({ clone: agent.slug });
    window.location.href = `/agents/new?${params}`;
  }, []);

  const handleArchive = useCallback(
    async (agent: Agent) => {
      if (!confirm(`Archive agent "${agent.name}"? This will deactivate it.`)) {
        return;
      }
      try {
        const res = await fetchApi(`/api/agents/${agent.slug}`, {
          method: "DELETE",
        });
        if (!res.ok) throw new Error("Failed to archive agent");
        refetch();
      } catch (err) {
        console.error("Archive failed:", err);
        alert("Failed to archive agent");
      }
    },
    [refetch]
  );

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* HEADER */}
      <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Bot className="h-5 w-5 text-slate-600 dark:text-slate-400" />
                <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100 tracking-tight">
                  Agents
                </h1>
              </div>
              <div className="flex items-center gap-3 text-xs font-mono tabular-nums">
                <span className="text-slate-500 dark:text-slate-400">
                  {data?.total ?? 0} total
                </span>
              </div>
            </div>

            {/* Controls */}
            <div className="flex items-center gap-2">
              {/* Search */}
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search agents..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8 pr-3 py-1.5 w-48 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500"
                />
              </div>

              {/* Show inactive toggle */}
              <label className="flex items-center gap-2 px-2.5 py-1.5 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  checked={showInactive}
                  onChange={(e) => setShowInactive(e.target.checked)}
                  className="rounded border-slate-300 dark:border-slate-600"
                />
                <span className="text-slate-600 dark:text-slate-400">Show inactive</span>
              </label>

              {/* Refresh */}
              <button
                onClick={() => refetch()}
                disabled={isRefetching}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors disabled:opacity-50"
              >
                <RefreshCw
                  className={cn("h-3.5 w-3.5", isRefetching && "animate-spin")}
                />
                Refresh
              </button>

              {/* New Agent */}
              <a
                href="/agents/new"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
                New Agent
              </a>
            </div>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-5">
        {/* Global Instructions Panel */}
        <GlobalInstructionsPanel
          activeAgentCount={data?.agents?.filter((a) => a.is_active).length ?? 0}
        />

        {/* Error State */}
        {error && (
          <div className="flex items-center gap-2 p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 mb-5">
            <AlertCircle className="h-4 w-4" />
            <p className="text-xs font-medium">Failed to load agents</p>
          </div>
        )}

        {/* Loading */}
        {isLoading && (
          <div className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
            <div className="h-10 bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-700" />
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="grid grid-cols-[200px_1fr_140px_100px_100px_100px_40px] gap-3 px-4 py-3 border-b border-slate-100 dark:border-slate-800/50"
              >
                <div className="h-4 w-32 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-4 w-48 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-5 w-20 rounded-full bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-4 w-16 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-4 w-12 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-4 w-12 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
                <div className="h-4 w-4 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              </div>
            ))}
          </div>
        )}

        {/* AGENTS TABLE */}
        {data && (
          <>
            {filteredAgents.length === 0 ? (
              <div className="text-center py-20 text-slate-400">
                <Bot className="h-10 w-10 mx-auto mb-3 opacity-30" />
                <p className="text-sm font-medium">No agents found</p>
              </div>
            ) : (
              <div className="bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm overflow-x-auto">
                {/* TABLE HEADER */}
                <div className="bg-slate-50/95 dark:bg-slate-800/95 border-b border-slate-200 dark:border-slate-700 min-w-[1100px]">
                  <div className="grid grid-cols-[180px_1fr_130px_130px_130px_130px_80px_40px] gap-3 px-4 py-2.5 items-center">
                    <SortableHeader label="Agent" field="name" currentField={sortField} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Model" field="model" currentField={sortField} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader label="Status" field="status" currentField={sortField} direction={sortDirection} onSort={handleSort} />
                    <SortableHeader
                      label="Requests 24h"
                      field="requests"
                      currentField={sortField}
                      direction={sortDirection}
                      onSort={handleSort}
                      icon={<Activity className="h-3 w-3" />}
                    />
                    <SortableHeader
                      label="Latency"
                      field="latency"
                      currentField={sortField}
                      direction={sortDirection}
                      onSort={handleSort}
                      icon={<Clock className="h-3 w-3" />}
                    />
                    <SortableHeader
                      label="Success"
                      field="success"
                      currentField={sortField}
                      direction={sortDirection}
                      onSort={handleSort}
                      icon={<CheckCircle2 className="h-3 w-3" />}
                    />
                    <SortableHeader label="Ver" field="version" currentField={sortField} direction={sortDirection} onSort={handleSort} align="right" />
                    <div />
                  </div>
                </div>

                {/* TABLE BODY */}
                <div className="divide-y divide-slate-100 dark:divide-slate-800/50 min-w-[1100px]">
                  {filteredAgents.map((agent) => {
                    const metrics = getMetrics(agent.slug);
                    return (
                      <div
                        key={agent.id}
                        className="grid grid-cols-[180px_1fr_130px_130px_130px_130px_80px_40px] gap-3 px-4 py-3 items-center hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors"
                      >
                        {/* Agent Name & Slug */}
                        <div className="min-w-0">
                          <a
                            href={`/agents/${agent.slug}`}
                            className="text-sm font-semibold text-slate-800 dark:text-slate-100 hover:text-blue-600 dark:hover:text-blue-400 truncate block"
                          >
                            {agent.name}
                          </a>
                          <span className="text-[10px] text-slate-400 font-mono">
                            {agent.slug}
                          </span>
                        </div>

                        {/* Model Stack */}
                        <div className="flex flex-wrap gap-1 items-center">
                          <ModelPill model={agent.primary_model_id} />
                          {agent.fallback_models.length > 0 && (
                            <span className="text-[10px] text-slate-400">
                              +{agent.fallback_models.length} fallback
                            </span>
                          )}
                        </div>

                        {/* Status */}
                        <StatusBadge isActive={agent.is_active} />

                        {/* Requests 24h with sparkline */}
                        <MetricCell
                          label="Requests"
                          value={metrics?.requests_24h ?? 0}
                          trend={metrics?.latency_trend}
                          color="blue"
                        />

                        {/* Latency with sparkline */}
                        <MetricCell
                          label="Latency"
                          value={metrics?.avg_latency_ms?.toFixed(0) ?? "—"}
                          unit="ms"
                          trend={metrics?.latency_trend}
                          color="amber"
                        />

                        {/* Success Rate with sparkline */}
                        <MetricCell
                          label="Success"
                          value={metrics?.success_rate?.toFixed(1) ?? "100.0"}
                          unit="%"
                          trend={metrics?.success_trend}
                          color="emerald"
                        />

                        {/* Version */}
                        <div className="text-right">
                          <span className="text-xs font-mono tabular-nums text-slate-500">
                            v{agent.version}
                          </span>
                        </div>

                        {/* Actions */}
                        <AgentActionsMenu
                          agent={agent}
                          onClone={handleClone}
                          onArchive={handleArchive}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
