import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { Download, Quote, ThumbsUp, ThumbsDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { MemoryAnalytics } from "@/lib/memory-api";
import { TIER_COLORS, TIER_LABELS } from "./analytics-constants";
import { EmptyChart } from "./analytics-components";

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

interface UsageStatsProps {
  data: MemoryAnalytics;
}

export function UsageStats({ data }: UsageStatsProps) {
  const items = [
    { label: "Loaded", value: data.total_loaded, icon: Download, color: "text-sky-400", bg: "bg-sky-500/10" },
    { label: "Cited", value: data.total_cited, icon: Quote, color: "text-emerald-400", bg: "bg-emerald-500/10" },
    { label: "Helpful", value: data.total_helpful, icon: ThumbsUp, color: "text-green-400", bg: "bg-green-500/10" },
    { label: "Harmful", value: data.total_harmful, icon: ThumbsDown, color: "text-amber-400", bg: "bg-amber-500/10" },
  ];

  return (
    <div className="grid grid-cols-2 gap-3">
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
