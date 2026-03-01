"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
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
import { EmptyState } from "./analytics-components";
import { LoadingState, ErrorState } from "./analytics-states";
import { AnalyticsContent } from "./analytics-content";

const QUERY_CONFIG = {
  refetchInterval: 60000,
  staleTime: 30000,
} as const;

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
    ...QUERY_CONFIG,
  });

  const { data: metrics } = useQuery<MetricsDashboard>({
    queryKey: ["memoryMetrics", days],
    queryFn: () => fetchMemoryMetrics({ days, period: "day" }),
    ...QUERY_CONFIG,
  });

  const { data: topMemories } = useQuery<TopMemory[]>({
    queryKey: ["topMemories", topMemoriesSortBy],
    queryFn: () => fetchTopMemories({ sortBy: topMemoriesSortBy, limit: 8 }),
    ...QUERY_CONFIG,
  });

  const { data: tierChanges } = useQuery<TierChangesSummary>({
    queryKey: ["tierChanges", days],
    queryFn: () => fetchTierChanges({ days }),
    ...QUERY_CONFIG,
  });

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState message={error.message} />;
  if (!analytics || analytics.total_episodes === 0) return <EmptyState />;

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
