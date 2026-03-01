"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Database,
  Quote,
  TrendingUp,
  Download,
  Layers,
  CheckCircle2,
  Activity,
  Trophy,
  Heart,
  ArrowUpDown,
} from "lucide-react";
import {
  fetchMemoryAnalytics,
  fetchMemoryMetrics,
  fetchTopMemories,
  fetchTierChanges,
  type MemoryAnalytics,
  type MetricsDashboard,
  type TopMemory,
  type TierChangesSummary,
} from "@/lib/memory-api";
import {
  MetricCard,
  SectionHeader,
  TimeRangeSelector,
  SkeletonCard,
  SkeletonSection,
  EmptyState,
} from "./analytics-components";
import {
  TierChart,
  ScopeChart,
  InjectionMetricsChart,
  FeedbackLoopsHealth,
  TopMemoriesTable,
  UsageStats,
} from "./analytics-charts";

function LoadingState() {
  return (
    <div className="p-4 space-y-4 overflow-auto">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
        <SkeletonCard />
        <SkeletonCard />
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
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SkeletonSection />
        <SkeletonSection />
      </div>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="p-4 rounded-full bg-red-900/20 mb-4">
        <BarChart3 className="w-8 h-8 text-red-400" />
      </div>
      <h3 className="text-lg font-medium text-slate-100 mb-1">Failed to Load Analytics</h3>
      <p className="text-sm text-red-400 max-w-sm">{message}</p>
    </div>
  );
}

interface AnalyticsContentProps {
  analytics: MemoryAnalytics;
  metrics: MetricsDashboard | undefined;
  topMemories: TopMemory[];
  tierChanges: TierChangesSummary | undefined;
  days: number;
  onDaysChange: (days: number) => void;
  topMemoriesSortBy: string;
  onTopMemoriesSortChange: (field: string) => void;
  onTierClick: (tier: string) => void;
  onMemoryClick: (uuid: string) => void;
}

function TierChangesSection({ data }: { data: TierChangesSummary | undefined }) {
  if (!data || data.total === 0) {
    return <p className="text-xs text-slate-500 text-center py-4">No tier changes recorded</p>;
  }

  const CHANGE_COLORS: Record<string, string> = {
    self_heal: "text-emerald-400",
    demotion: "text-red-400",
    promotion: "text-blue-400",
    retirement: "text-slate-400",
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {Object.entries(data.by_type).map(([type, info]) => (
          <div key={type} className="p-2 rounded bg-slate-800/40 border border-slate-800/60">
            <p className={`text-sm font-mono font-bold ${CHANGE_COLORS[type] ?? "text-slate-300"}`}>
              {info.count}
            </p>
            <p className="text-[9px] text-slate-500 uppercase">{type.replace("_", " ")}</p>
          </div>
        ))}
      </div>
      {data.recent.length > 0 && (
        <div className="space-y-1 max-h-48 overflow-y-auto">
          {data.recent.slice(0, 10).map((entry, i) => (
            <div key={i} className="flex items-center gap-2 px-2 py-1 text-[10px] rounded bg-slate-800/20">
              <span className={`font-medium ${CHANGE_COLORS[entry.change_type] ?? "text-slate-400"}`}>
                {entry.change_type.replace("_", " ")}
              </span>
              <span className="text-slate-600">|</span>
              <span className="text-slate-500">{entry.old_tier} → {entry.new_tier}</span>
              {entry.lifecycle_score_before != null && entry.lifecycle_score_after != null && (
                <>
                  <span className="text-slate-600">|</span>
                  <span className="text-slate-500 font-mono">
                    {(entry.lifecycle_score_before * 100).toFixed(0)} → {(entry.lifecycle_score_after * 100).toFixed(0)}
                  </span>
                </>
              )}
              <span className="text-slate-600 ml-auto font-mono">
                {entry.episode_uuid.slice(0, 8)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AnalyticsContent({
  analytics,
  metrics,
  topMemories,
  tierChanges,
  days,
  onDaysChange,
  topMemoriesSortBy,
  onTopMemoriesSortChange,
  onTierClick,
  onMemoryClick,
}: AnalyticsContentProps) {
  return (
    <div className="p-4 space-y-4 overflow-auto">
      {/* Header with time range */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide">
          Memory Analytics
        </h2>
        <TimeRangeSelector value={days} onChange={onDaysChange} />
      </div>

      {/* Row 1: KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
        <MetricCard
          label="Total Episodes"
          value={analytics.total_episodes.toLocaleString()}
          icon={Database}
          color="emerald"
        />
        <MetricCard
          label="Success Rate"
          value={`${(analytics.success_rate * 100).toFixed(1)}%`}
          icon={CheckCircle2}
          color="green"
        />
        <MetricCard
          label="Citation Rate"
          value={`${(analytics.citation_rate * 100).toFixed(1)}%`}
          icon={Quote}
          color="purple"
        />
        <MetricCard
          label="Avg Utility"
          value={analytics.avg_utility_score.toFixed(2)}
          icon={TrendingUp}
          color="sky"
        />
        <MetricCard
          label="Avg Lifecycle"
          value={analytics.avg_lifecycle_score.toFixed(2)}
          icon={Heart}
          color="rose"
        />
        <MetricCard
          label="Total Loaded"
          value={analytics.total_loaded.toLocaleString()}
          icon={Download}
          color="amber"
        />
      </div>

      {/* Row 2: 3-column grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
          <SectionHeader title="Tier Distribution" icon={Layers} />
          <TierChart data={analytics.tier_distribution} onTierClick={onTierClick} />
        </div>

        <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
          <SectionHeader title="Scope Distribution" icon={Database} />
          <ScopeChart data={analytics.scope_distribution} />
        </div>

        <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
          <SectionHeader title="Feedback Loops" icon={Activity} />
          <FeedbackLoopsHealth analytics={analytics} metrics={metrics} />
        </div>
      </div>

      {/* Row 3: Full-width injection metrics chart */}
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
        <SectionHeader title="Injection Metrics Over Time" icon={TrendingUp} />
        <InjectionMetricsChart data={metrics} />
      </div>

      {/* Row 4: 3-column grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
          <SectionHeader title="Usage Stats" icon={BarChart3} />
          <UsageStats data={analytics} />
        </div>

        <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
          <SectionHeader title="Top Performing Memories" icon={Trophy} />
          <TopMemoriesTable
            data={topMemories}
            sortBy={topMemoriesSortBy}
            onSortChange={onTopMemoriesSortChange}
            onRowClick={onMemoryClick}
          />
        </div>

        <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5">
          <SectionHeader title="Tier Changes" icon={ArrowUpDown} />
          <TierChangesSection data={tierChanges} />
        </div>
      </div>
    </div>
  );
}

export function AnalyticsTab() {
  const router = useRouter();
  const [days, setDays] = useState(30);
  const [topMemoriesSortBy, setTopMemoriesSortBy] = useState("utility_score");

  const navigateToEpisodes = useCallback(
    (filter: Record<string, string>) => {
      const params = new URLSearchParams(filter);
      router.push(`/memory?${params.toString()}`, { scroll: false });
    },
    [router]
  );

  const navigateToEpisode = useCallback(
    (uuid: string) => {
      router.push(`/memory?episode=${uuid}`, { scroll: false });
    },
    [router]
  );

  const { data: analytics, isLoading, error } = useQuery<MemoryAnalytics>({
    queryKey: ["memoryAnalytics", days],
    queryFn: () => fetchMemoryAnalytics({ days }),
    refetchInterval: 60000,
    staleTime: 30000,
  });

  const { data: metrics } = useQuery<MetricsDashboard>({
    queryKey: ["memoryMetrics", days],
    queryFn: () => fetchMemoryMetrics({ days, period: "day" }),
    refetchInterval: 60000,
    staleTime: 30000,
  });

  const { data: topMemories } = useQuery<TopMemory[]>({
    queryKey: ["topMemories", topMemoriesSortBy],
    queryFn: () => fetchTopMemories({ sortBy: topMemoriesSortBy, limit: 8 }),
    refetchInterval: 60000,
    staleTime: 30000,
  });

  const { data: tierChanges } = useQuery<TierChangesSummary>({
    queryKey: ["tierChanges", days],
    queryFn: () => fetchTierChanges({ days }),
    refetchInterval: 60000,
    staleTime: 30000,
  });

  if (isLoading) {
    return <LoadingState />;
  }

  if (error) {
    return <ErrorState message={error.message} />;
  }

  if (!analytics || analytics.total_episodes === 0) {
    return <EmptyState />;
  }

  return (
    <AnalyticsContent
      analytics={analytics}
      metrics={metrics}
      topMemories={topMemories ?? []}
      tierChanges={tierChanges}
      days={days}
      onDaysChange={setDays}
      topMemoriesSortBy={topMemoriesSortBy}
      onTopMemoriesSortChange={setTopMemoriesSortBy}
      onTierClick={(tier) => navigateToEpisodes({ category: tier })}
      onMemoryClick={navigateToEpisode}
    />
  );
}
