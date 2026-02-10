import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ComposedChart,
  Line,
} from "recharts";
import {
  Download,
  Quote,
  ThumbsUp,
  ThumbsDown,
  CheckCircle2,
  Zap,
  ArrowUpDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { MemoryAnalytics, MetricsDashboard, TopMemory } from "@/lib/memory-api";
import { TIER_COLORS, TIER_LABELS } from "./analytics-constants";
import { EmptyChart, StatusDot } from "./analytics-components";

interface TierChartProps {
  data: MemoryAnalytics["tier_distribution"];
  onTierClick?: (tier: string) => void;
}

export function TierChart({ data, onTierClick }: TierChartProps) {
  if (data.length === 0) return <EmptyChart label="No tier data" />;

  const chartData = data.map((d) => ({
    name: TIER_LABELS[d.tier] || d.tier,
    count: d.count,
    percentage: d.percentage,
    fill: TIER_COLORS[d.tier] || "#64748b",
  }));

  return (
    <div className="space-y-3">
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
          <BarChart data={chartData} layout="vertical" barCategoryGap="30%">
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="name"
              width={80}
              tick={{ fill: "#94a3b8", fontSize: 12 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0].payload;
                return (
                  <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 shadow-xl">
                    <p className="text-sm font-medium text-slate-100">
                      {d.name}
                    </p>
                    <p className="text-xs text-slate-400">
                      {d.count} episodes ({d.percentage}%)
                    </p>
                  </div>
                );
              }}
            />
            <Bar
              dataKey="count"
              radius={[0, 4, 4, 0]}
              maxBarSize={24}
              cursor={onTierClick ? "pointer" : undefined}
              onClick={(_data, _index, e) => {
                const target = e?.target as SVGElement | undefined;
                const barIndex = target ? chartData.findIndex((d) => d.fill === target.getAttribute("fill")) : -1;
                const entry = barIndex >= 0 ? chartData[barIndex] : null;
                const tierKey = entry ? Object.entries(TIER_LABELS).find(([, label]) => label === entry.name)?.[0] : null;
                if (tierKey && onTierClick) onTierClick(tierKey);
              }}
            >
              {chartData.map((entry) => (
                <Cell key={entry.name} fill={entry.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="flex gap-4 justify-center">
        {chartData.map((d) => (
          <div key={d.name} className="flex items-center gap-1.5 text-xs text-slate-400">
            <span
              className="w-2.5 h-2.5 rounded-sm"
              style={{ backgroundColor: d.fill }}
            />
            {d.name} ({d.count})
          </div>
        ))}
      </div>
    </div>
  );
}

interface ScopeChartProps {
  data: MemoryAnalytics["scope_distribution"];
}

export function ScopeChart({ data }: ScopeChartProps) {
  if (data.length === 0) return <EmptyChart label="No scope data" />;

  return (
    <div className="space-y-3">
      {data.map((d) => (
        <div key={d.scope}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm text-slate-300 capitalize">{d.scope}</span>
            <span className="text-sm font-mono text-slate-400">
              {d.count} ({d.percentage}%)
            </span>
          </div>
          <div className="h-3 rounded-full bg-slate-800 overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                d.scope === "global" ? "bg-indigo-500" : "bg-teal-500"
              )}
              style={{ width: `${d.percentage}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

interface TrendChartProps {
  data: MemoryAnalytics["daily_trend"];
}

export function TrendChart({ data }: TrendChartProps) {
  if (data.length === 0) return <EmptyChart label="No trend data for this period" />;

  const chartData = data.map((d) => ({
    date: d.date.slice(5),
    count: d.count,
  }));

  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
        <BarChart data={chartData} barCategoryGap="20%">
          <XAxis
            dataKey="date"
            tick={{ fill: "#64748b", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            interval={Math.max(0, Math.floor(chartData.length / 8) - 1)}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: "#64748b", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={30}
          />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              return (
                <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 shadow-xl">
                  <p className="text-xs text-slate-400">{label}</p>
                  <p className="text-sm font-medium text-slate-100">
                    {payload[0].value} episodes
                  </p>
                </div>
              );
            }}
          />
          <Bar dataKey="count" fill="#10b981" radius={[3, 3, 0, 0]} maxBarSize={20} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

interface InjectionMetricsChartProps {
  data: MetricsDashboard | undefined;
}

export function InjectionMetricsChart({ data }: InjectionMetricsChartProps) {
  if (!data || data.by_period.length === 0) {
    return <EmptyChart label="No injection metrics for this period" />;
  }

  const chartData = data.by_period.map((d) => ({
    period: d.period.slice(5),
    injections: d.injection_count,
    successRate: Math.round(d.avg_success_rate * 100),
    citationRate: Math.round(d.avg_citation_rate * 100),
  }));

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
        <ComposedChart data={chartData} barCategoryGap="20%">
          <XAxis
            dataKey="period"
            tick={{ fill: "#64748b", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            interval={Math.max(0, Math.floor(chartData.length / 10) - 1)}
          />
          <YAxis
            yAxisId="left"
            allowDecimals={false}
            tick={{ fill: "#64748b", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={35}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            domain={[0, 100]}
            tick={{ fill: "#64748b", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={35}
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              return (
                <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 shadow-xl">
                  <p className="text-xs text-slate-400 mb-1">{label}</p>
                  {payload.map((p) => (
                    <p key={p.dataKey as string} className="text-xs text-slate-200">
                      <span style={{ color: p.color }}>{p.name}</span>:{" "}
                      {p.dataKey === "injections" ? p.value : `${p.value}%`}
                    </p>
                  ))}
                </div>
              );
            }}
          />
          <Bar
            yAxisId="left"
            dataKey="injections"
            name="Injections"
            fill="#475569"
            radius={[3, 3, 0, 0]}
            maxBarSize={24}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="successRate"
            name="Success %"
            stroke="#22c55e"
            strokeWidth={2}
            dot={false}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="citationRate"
            name="Citation %"
            stroke="#a855f7"
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="flex gap-5 justify-center mt-2">
        <div className="flex items-center gap-1.5 text-xs text-slate-400">
          <span className="w-3 h-2 rounded-sm bg-slate-600" />
          Injections
        </div>
        <div className="flex items-center gap-1.5 text-xs text-slate-400">
          <span className="w-3 h-0.5 rounded-full bg-green-500" />
          Success %
        </div>
        <div className="flex items-center gap-1.5 text-xs text-slate-400">
          <span className="w-3 h-0.5 rounded-full bg-purple-500" />
          Citation %
        </div>
      </div>
    </div>
  );
}

interface FeedbackLoopsHealthProps {
  analytics: MemoryAnalytics;
  metrics: MetricsDashboard | undefined;
}

function getLoopStatus(value: number): "active" | "warning" | "inactive" {
  if (value > 0) return "active";
  return "inactive";
}

export function FeedbackLoopsHealth({ analytics, metrics }: FeedbackLoopsHealthProps) {
  const loops = [
    {
      name: "Citation Scanning",
      description: "CC hook scans for [M:id]/[G:id]/[R:id] citations",
      stat: `${analytics.total_cited} cited`,
      status: getLoopStatus(analytics.total_cited),
    },
    {
      name: "Task Outcome",
      description: "Task success/failure credited to injected memories",
      stat: `${analytics.total_success} succeeded`,
      status: getLoopStatus(analytics.total_success),
    },
    {
      name: "Utility Scoring",
      description: "3-tier formula: citations + success + recency",
      stat: `${analytics.avg_utility_score.toFixed(2)} avg`,
      status: getLoopStatus(analytics.avg_utility_score),
    },
  ];

  return (
    <div className="space-y-3">
      {loops.map((loop) => (
        <div
          key={loop.name}
          className="flex items-center gap-3 p-3 rounded-lg bg-slate-800/40 border border-slate-800/60"
        >
          <StatusDot status={loop.status} />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-200">{loop.name}</p>
            <p className="text-[10px] text-slate-500 truncate">{loop.description}</p>
          </div>
          <span className="text-xs font-mono text-slate-400 shrink-0">{loop.stat}</span>
        </div>
      ))}
      {metrics && (
        <div className="pt-1 text-[10px] text-slate-500 text-center">
          {metrics.total_injections} total injections tracked
        </div>
      )}
    </div>
  );
}

interface TopMemoriesTableProps {
  data: TopMemory[];
  sortBy: string;
  onSortChange: (field: string) => void;
  onRowClick?: (uuid: string) => void;
}

const SORT_OPTIONS = [
  { field: "utility_score", label: "Utility" },
  { field: "referenced_count", label: "Citations" },
  { field: "success_count", label: "Success" },
] as const;

const TIER_DOT_COLORS: Record<string, string> = {
  mandate: "bg-red-500",
  guardrail: "bg-amber-500",
  reference: "bg-blue-500",
};

export function TopMemoriesTable({ data, sortBy, onSortChange, onRowClick }: TopMemoriesTableProps) {
  if (data.length === 0) return <EmptyChart label="No memories with usage data" />;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5">
        <ArrowUpDown className="h-3 w-3 text-slate-500" />
        {SORT_OPTIONS.map((opt) => (
          <button
            key={opt.field}
            onClick={() => onSortChange(opt.field)}
            className={cn(
              "px-2 py-0.5 text-[10px] font-medium rounded transition-colors",
              sortBy === opt.field
                ? "bg-purple-600/30 text-purple-300"
                : "text-slate-500 hover:text-slate-300"
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>
      <div className="space-y-1">
        {data.map((mem) => (
          <button
            key={mem.uuid}
            onClick={() => onRowClick?.(mem.uuid)}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md bg-slate-800/30 hover:bg-slate-800/60 transition-colors text-left group"
          >
            <span
              className={cn(
                "w-1.5 h-1.5 rounded-full shrink-0",
                TIER_DOT_COLORS[mem.injection_tier] ?? "bg-slate-500"
              )}
            />
            <span className="text-xs text-slate-300 truncate flex-1 min-w-0">
              {mem.content}
            </span>
            <span className="text-[10px] font-mono text-slate-500 shrink-0 tabular-nums">
              {mem.utility_score.toFixed(1)}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

interface UsageStatsProps {
  data: MemoryAnalytics;
}

export function UsageStats({ data }: UsageStatsProps) {
  const items = [
    { label: "Loaded", value: data.total_loaded, icon: Download, color: "text-sky-400", bg: "bg-sky-500/10" },
    { label: "Cited", value: data.total_cited, icon: Quote, color: "text-emerald-400", bg: "bg-emerald-500/10" },
    { label: "Success", value: data.total_success, icon: CheckCircle2, color: "text-green-400", bg: "bg-green-500/10" },
    { label: "Helpful", value: data.total_helpful, icon: ThumbsUp, color: "text-teal-400", bg: "bg-teal-500/10" },
    { label: "Harmful", value: data.total_harmful, icon: ThumbsDown, color: "text-amber-400", bg: "bg-amber-500/10" },
    { label: "Injections", value: data.total_loaded + data.total_cited, icon: Zap, color: "text-violet-400", bg: "bg-violet-500/10" },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
      {items.map((item) => (
        <div
          key={item.label}
          className="flex items-center gap-3 p-4 rounded-lg bg-slate-900/60 border border-slate-800/80 hover:shadow-lg hover:shadow-black/20 transition-all duration-200"
        >
          <div className={cn("p-2 rounded-md", item.bg)}>
            <item.icon className={cn("h-4 w-4", item.color)} />
          </div>
          <div>
            <p className="text-xl font-semibold text-slate-50 font-mono tabular-nums">
              {item.value.toLocaleString()}
            </p>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">{item.label}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
