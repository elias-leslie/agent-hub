"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Database,
  Quote,
  TrendingUp,
  Download,
  Layers,
} from "lucide-react";
import { fetchMemoryAnalytics, type MemoryAnalytics } from "@/lib/memory-api";
import {
  MetricCard,
  SectionHeader,
  SkeletonCard,
  SkeletonSection,
  EmptyState,
} from "./analytics-components";
import {
  TierChart,
  ScopeChart,
  TrendChart,
  UsageStats,
} from "./analytics-charts";

function LoadingState() {
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
  data: MemoryAnalytics;
  onTierClick: (tier: string) => void;
}

function AnalyticsContent({ data, onTierClick }: AnalyticsContentProps) {
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
          <TierChart data={data.tier_distribution} onTierClick={onTierClick} />
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

export function AnalyticsTab() {
  const router = useRouter();

  const navigateToEpisodes = useCallback(
    (filter: Record<string, string>) => {
      const params = new URLSearchParams(filter);
      router.push(`/memory?${params.toString()}`, { scroll: false });
    },
    [router]
  );

  const { data, isLoading, error } = useQuery<MemoryAnalytics>({
    queryKey: ["memoryAnalytics"],
    queryFn: () => fetchMemoryAnalytics(),
    refetchInterval: 60000,
    staleTime: 30000,
  });

  if (isLoading) {
    return <LoadingState />;
  }

  if (error) {
    return <ErrorState message={error.message} />;
  }

  if (!data || data.total_episodes === 0) {
    return <EmptyState />;
  }

  return (
    <AnalyticsContent
      data={data}
      onTierClick={(tier) => navigateToEpisodes({ category: tier })}
    />
  );
}
