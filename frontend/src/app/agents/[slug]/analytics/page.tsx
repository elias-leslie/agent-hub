"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  DollarSign,
  Clock,
  AlertTriangle,
  Activity,
  Loader2,
  AlertCircle,
  Sigma,
} from "lucide-react";
import { fetchAgent, fetchAgentMetrics } from "@/lib/api";
import { metricsToAnalytics, sliceTrendWindow } from "./utils";
import { KPICard } from "./components/KPICard";
import { ChartCard } from "./components/ChartCard";
import { AnalyticsHeader } from "./components/AnalyticsHeader";
import { ChartSection } from "./components/ChartSection";
import type { AnalyticsWindow } from "./types";

export default function AgentAnalyticsPage() {
  const params = useParams();
  const slug = params.slug as string;
  const [timeRange, setTimeRange] = useState<AnalyticsWindow>(24);

  const {
    data: agent,
    isLoading: agentLoading,
    error: agentError,
    refetch: refetchAgent,
    isRefetching: agentRefetching,
  } = useQuery({
    queryKey: ["agent", slug],
    queryFn: () => fetchAgent(slug),
    enabled: !!slug,
  });

  const {
    data: metrics,
    isLoading: metricsLoading,
    error: metricsError,
    refetch: refetchMetrics,
    isRefetching: metricsRefetching,
  } = useQuery({
    queryKey: ["agent-metrics", slug],
    queryFn: () => fetchAgentMetrics(slug),
    enabled: !!slug,
  });

  const isLoading = agentLoading || metricsLoading;
  const error = agentError || metricsError;
  const analytics = agent && metrics ? metricsToAnalytics(metrics, agent) : null;
  const visibleTrend = analytics ? sliceTrendWindow(analytics.trend, timeRange) : [];
  const isRefreshing = agentRefetching || metricsRefetching;
  const hasRecentActivity = analytics
    ? analytics.totalRequests > 0 || analytics.totalTokens > 0 || analytics.totalCostUsd > 0
    : false;

  function handleRefresh() {
    void Promise.all([refetchAgent(), refetchMetrics()]);
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    );
  }

  if (error) {
    const errorMessage = error instanceof Error ? error.message : "Failed to load analytics";

    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center px-6">
        <div className="max-w-md text-center">
          <AlertCircle className="h-10 w-10 text-red-500 mx-auto mb-3" />
          <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
            Failed to load analytics
          </p>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            {errorMessage}
          </p>
        </div>
      </div>
    );
  }

  if (!agent || !analytics) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="h-10 w-10 text-red-500 mx-auto mb-3" />
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Agent not found
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      <AnalyticsHeader
        agentName={agent.name}
        slug={slug}
        timeRange={timeRange}
        onTimeRangeChange={setTimeRange}
        onRefresh={handleRefresh}
        isRefreshing={isRefreshing}
      />

      <main className="p-6 lg:p-8 max-w-7xl mx-auto">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <KPICard
            label="Total Cost"
            value={`$${analytics.totalCostUsd.toFixed(2)}`}
            icon={DollarSign}
            color="blue"
          />
          <KPICard
            label="Avg Latency"
            value={analytics.avgLatencyMs}
            unit="ms"
            icon={Clock}
            color="amber"
          />
          <KPICard
            label="Error Rate"
            value={`${analytics.errorRate}%`}
            icon={AlertTriangle}
            color="red"
          />
          <KPICard
            label="Success Rate"
            value={`${analytics.successRate}%`}
            icon={Activity}
            color="green"
          />
        </div>

        {hasRecentActivity ? (
          <ChartSection trend={visibleTrend} />
        ) : (
          <ChartCard title="Activity window">
            <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-6 py-10 text-center dark:border-slate-700 dark:bg-slate-900/40">
              <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                No recent activity
              </p>
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                This agent has not handled any requests in the last 24 hours yet.
              </p>
            </div>
          </ChartCard>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <ChartCard title="24h Throughput">
            <div className="space-y-4">
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500 dark:text-slate-400">Requests</span>
                <span className="font-semibold text-slate-900 dark:text-slate-100">
                  {analytics.totalRequests}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500 dark:text-slate-400">Requests / hour</span>
                <span className="font-semibold text-slate-900 dark:text-slate-100">
                  {analytics.requestsPerHour}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-500 dark:text-slate-400">Tokens</span>
                <span className="font-semibold text-slate-900 dark:text-slate-100">
                  {analytics.totalTokens.toLocaleString()}
                </span>
              </div>
            </div>
          </ChartCard>

          <ChartCard title="Model Routing">
            <div className="space-y-2">
              {analytics.modelSummary.map((model) => (
                <div
                  key={model}
                  className="flex items-center justify-between rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-2 text-sm"
                >
                  <span className="text-slate-600 dark:text-slate-300 break-all">
                    {model}
                  </span>
                  <Sigma className="h-4 w-4 text-slate-400" />
                </div>
              ))}
            </div>
          </ChartCard>

          <ChartCard title="Freshness">
            <div className="space-y-4 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-slate-500 dark:text-slate-400">Visible window</span>
                <span className="font-semibold text-slate-900 dark:text-slate-100">
                  Last {timeRange}h
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500 dark:text-slate-400">Metrics basis</span>
                <span className="font-semibold text-slate-900 dark:text-slate-100">24h aggregate</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500 dark:text-slate-400">Agent updated</span>
                <span className="font-semibold text-slate-900 dark:text-slate-100">
                  {new Date(analytics.lastUpdatedAt).toLocaleString()}
                </span>
              </div>
            </div>
          </ChartCard>
        </div>
      </main>
    </div>
  );
}
