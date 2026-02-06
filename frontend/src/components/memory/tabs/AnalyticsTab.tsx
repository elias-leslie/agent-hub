"use client";

import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Database,
  Quote,
  TrendingUp,
  Download,
  ThumbsUp,
  ThumbsDown,
  Layers,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { cn } from "@/lib/utils";
import { fetchMemoryAnalytics, type MemoryAnalytics } from "@/lib/memory-api";

function MetricCard({
  label,
  value,
  icon: Icon,
  color = "emerald",
}: {
  label: string;
  value: string;
  icon: React.ComponentType<{ className?: string }>;
  color?: "emerald" | "amber" | "purple" | "sky";
}) {
  const colorMap = {
    emerald: {
      border: "border-l-emerald-500",
      iconBg: "bg-emerald-500/10",
      iconText: "text-emerald-400",
    },
    amber: {
      border: "border-l-amber-500",
      iconBg: "bg-amber-500/10",
      iconText: "text-amber-400",
    },
    purple: {
      border: "border-l-purple-500",
      iconBg: "bg-purple-500/10",
      iconText: "text-purple-400",
    },
    sky: {
      border: "border-l-sky-500",
      iconBg: "bg-sky-500/10",
      iconText: "text-sky-400",
    },
  };

  const c = colorMap[color];

  return (
    <div
      className={cn(
        "bg-slate-900/60 border border-slate-800/80 border-l-[3px] rounded-lg p-4",
        c.border,
        "hover:shadow-lg hover:shadow-black/20 transition-all duration-200"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
            {label}
          </span>
          <p className="mt-1.5 text-2xl font-semibold tracking-tight text-slate-50 font-mono tabular-nums">
            {value}
          </p>
        </div>
        <div className={cn("p-2 rounded-md", c.iconBg)}>
          <Icon className={cn("h-4 w-4", c.iconText)} />
        </div>
      </div>
    </div>
  );
}

function SectionHeader({
  title,
  icon: Icon,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className="h-4 w-4 text-purple-400" />
      <h3 className="text-sm font-semibold text-slate-200 uppercase tracking-wide">
        {title}
      </h3>
    </div>
  );
}

const TIER_COLORS: Record<string, string> = {
  mandate: "#ef4444",
  guardrail: "#f59e0b",
  reference: "#3b82f6",
};

const TIER_LABELS: Record<string, string> = {
  mandate: "Mandate",
  guardrail: "Guardrail",
  reference: "Reference",
};

function TierChart({ data }: { data: MemoryAnalytics["tier_distribution"] }) {
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
            <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={24}>
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

function ScopeChart({ data }: { data: MemoryAnalytics["scope_distribution"] }) {
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

function TrendChart({ data }: { data: MemoryAnalytics["daily_trend"] }) {
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

function UsageStats({ data }: { data: MemoryAnalytics }) {
  const items = [
    { label: "Loaded", value: data.total_loaded, icon: Download, color: "text-sky-400" },
    { label: "Cited", value: data.total_cited, icon: Quote, color: "text-emerald-400" },
    { label: "Helpful", value: data.total_helpful, icon: ThumbsUp, color: "text-green-400" },
    { label: "Harmful", value: data.total_harmful, icon: ThumbsDown, color: "text-amber-400" },
  ];

  return (
    <div className="grid grid-cols-2 gap-3">
      {items.map((item) => (
        <div
          key={item.label}
          className="flex items-center gap-3 p-3 rounded-lg bg-slate-800/40 border border-slate-800/60"
        >
          <item.icon className={cn("h-4 w-4", item.color)} />
          <div>
            <p className="text-lg font-semibold text-slate-100 font-mono tabular-nums">
              {item.value.toLocaleString()}
            </p>
            <p className="text-xs text-slate-400">{item.label}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-32 text-sm text-slate-500">
      {label}
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-4 animate-pulse">
      <div className="h-3 w-20 bg-slate-700 rounded mb-3" />
      <div className="h-7 w-16 bg-slate-700 rounded" />
    </div>
  );
}

function SkeletonSection() {
  return (
    <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5 animate-pulse">
      <div className="h-3 w-32 bg-slate-700 rounded mb-4" />
      <div className="space-y-3">
        <div className="h-6 w-full bg-slate-800 rounded" />
        <div className="h-6 w-3/4 bg-slate-800 rounded" />
        <div className="h-6 w-1/2 bg-slate-800 rounded" />
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="p-4 rounded-full bg-slate-800 mb-4">
        <BarChart3 className="w-8 h-8 text-slate-400" />
      </div>
      <h3 className="text-lg font-medium text-slate-100 mb-1">No Analytics Data</h3>
      <p className="text-sm text-slate-400 max-w-sm">
        Analytics will appear once episodes are created and used in memory injection.
      </p>
    </div>
  );
}

export function AnalyticsTab() {
  const { data, isLoading, error } = useQuery<MemoryAnalytics>({
    queryKey: ["memoryAnalytics"],
    queryFn: () => fetchMemoryAnalytics(),
    refetchInterval: 60000,
    staleTime: 30000,
  });

  if (isLoading) {
    return (
      <div className="p-4 space-y-4 overflow-auto">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <SkeletonSection />
          <SkeletonSection />
          <SkeletonSection />
        </div>
        <SkeletonSection />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <div className="p-4 rounded-full bg-red-900/20 mb-4">
          <BarChart3 className="w-8 h-8 text-red-400" />
        </div>
        <h3 className="text-lg font-medium text-slate-100 mb-1">Failed to Load Analytics</h3>
        <p className="text-sm text-red-400 max-w-sm">{error.message}</p>
      </div>
    );
  }

  if (!data || data.total_episodes === 0) {
    return <EmptyState />;
  }

  return (
    <div className="p-4 space-y-4 overflow-auto">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricCard
          label="Total Episodes"
          value={data.total_episodes.toLocaleString()}
          icon={Database}
          color="emerald"
        />
        <MetricCard
          label="Citation Rate"
          value={`${(data.citation_rate * 100).toFixed(1)}%`}
          icon={Quote}
          color="purple"
        />
        <MetricCard
          label="Avg Utility"
          value={data.avg_utility_score.toFixed(2)}
          icon={TrendingUp}
          color="sky"
        />
        <MetricCard
          label="Total Loaded"
          value={data.total_loaded.toLocaleString()}
          icon={Download}
          color="amber"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
          <SectionHeader title="Tier Distribution" icon={Layers} />
          <TierChart data={data.tier_distribution} />
        </div>

        <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
          <SectionHeader title="Scope Distribution" icon={Database} />
          <ScopeChart data={data.scope_distribution} />
        </div>

        <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
          <SectionHeader title="Usage Stats" icon={BarChart3} />
          <UsageStats data={data} />
        </div>
      </div>

      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Episode Creation Trend (30d)" icon={TrendingUp} />
        <TrendChart data={data.daily_trend} />
      </div>
    </div>
  );
}
