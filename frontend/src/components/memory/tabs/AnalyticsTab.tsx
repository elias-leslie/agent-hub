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
} from "lucide-react";
import {
  fetchMemoryAnalytics,
  fetchMemoryMetrics,
  fetchTopMemories,
  type MemoryAnalytics,
  type MetricsDashboard,
  type TopMemory,
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
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
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
  days: number;
  onDaysChange: (days: number) => void;
  topMemoriesSortBy: string;
  onTopMemoriesSortChange: (field: string) => void;
  onTierClick: (tier: string) => void;
  onMemoryClick: (uuid: string) => void;
}

function AnalyticsContent({
  analytics,
  metrics,
  topMemories,
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
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
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

      {/* Row 4: 2-column grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
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
      days={days}
      onDaysChange={setDays}
      topMemoriesSortBy={topMemoriesSortBy}
      onTopMemoriesSortChange={setTopMemoriesSortBy}
      onTierClick={(tier) => navigateToEpisodes({ category: tier })}
      onMemoryClick={navigateToEpisode}
    />
  );
}
