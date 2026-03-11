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
import { fetchAgent, fetchAgentBenchmarkDashboard, fetchAgentMetrics } from "@/lib/api";
import { BenchmarkTrendSection } from "./components/BenchmarkTrendSection";
import {
  filterBenchmarkTrendWindow,
  metricsToAnalytics,
  sliceTrendWindow,
} from "./utils";
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
  const {
    data: benchmarkDashboard,
    error: benchmarkError,
    refetch: refetchBenchmarks,
    isRefetching: benchmarksRefetching,
  } = useQuery({
    queryKey: ["agent-benchmarks", slug],
    queryFn: () => fetchAgentBenchmarkDashboard(slug),
    enabled: !!slug,
  });

  const isLoading = agentLoading || metricsLoading;
  const error = agentError || metricsError;
  const analytics = agent && metrics ? metricsToAnalytics(metrics, agent) : null;
  const visibleTrend = analytics ? sliceTrendWindow(analytics.trend, timeRange) : [];
  const visibleBenchmarkTrend = benchmarkDashboard
    ? filterBenchmarkTrendWindow(benchmarkDashboard.trend, timeRange)
    : [];
  const isRefreshing = agentRefetching || metricsRefetching || benchmarksRefetching;
  const hasRecentActivity = analytics
    ? analytics.totalRequests > 0 || analytics.totalTokens > 0 || analytics.totalCostUsd > 0
    : false;
  const hasBenchmarkHistory = benchmarkDashboard
    ? benchmarkDashboard.overview.total_runs > 0
    : false;

  function handleRefresh() {
    void Promise.all([refetchAgent(), refetchMetrics(), refetchBenchmarks()]);
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

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <KPICard
            label="Benchmark Runs"
            value={benchmarkDashboard?.overview.total_runs ?? 0}
            icon={Sigma}
            color="blue"
          />
          <KPICard
            label="Avg Benchmark Score"
            value={benchmarkDashboard?.overview.avg_score ?? 0}
            icon={Activity}
            color="green"
          />
          <KPICard
            label="Benchmark Pass Rate"
            value={`${benchmarkDashboard?.overview.pass_rate ?? 0}%`}
            icon={Clock}
            color="amber"
          />
          <KPICard
            label="Open Regressions"
            value={benchmarkDashboard?.overview.open_regressions ?? 0}
            icon={AlertTriangle}
            color="red"
          />
        </div>

        {benchmarkError ? (
          <ChartCard title="Benchmark Observability">
            <div className="rounded-lg border border-dashed border-red-300 bg-red-50 px-6 py-10 text-center dark:border-red-900 dark:bg-red-950/20">
              <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                Benchmark history unavailable
              </p>
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                {benchmarkError instanceof Error
                  ? benchmarkError.message
                  : "Failed to load persisted benchmark history."}
              </p>
            </div>
          </ChartCard>
        ) : hasBenchmarkHistory ? (
          <BenchmarkTrendSection trend={visibleBenchmarkTrend} />
        ) : (
          <ChartCard title="Benchmark Observability">
            <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-6 py-10 text-center dark:border-slate-700 dark:bg-slate-900/40">
              <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                No persisted benchmark runs yet
              </p>
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                Run the Jenny benchmark or honing workflow to start tracking regression and model
                trends here.
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

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 mt-6">
          <ChartCard title="Open Regressions">
            <div className="space-y-3">
              {(benchmarkDashboard?.open_regressions ?? []).length > 0 ? (
                benchmarkDashboard?.open_regressions.map((cluster) => (
                  <div
                    key={cluster.regression_key}
                    className="rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-3"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        {cluster.case_id}
                      </p>
                      <span className="text-xs font-medium text-red-600 dark:text-red-400">
                        {cluster.occurrence_count} hits
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {cluster.failure_detail}
                    </p>
                    <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                      Models: {cluster.affected_models.join(", ") || "n/a"}
                    </p>
                  </div>
                ))
              ) : (
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  No open benchmark regressions are currently tracked.
                </p>
              )}
            </div>
          </ChartCard>

          <ChartCard title="Recent Benchmark Runs">
            <div className="space-y-3">
              {(benchmarkDashboard?.recent_runs ?? []).slice(0, 6).map((run) => (
                <div
                  key={run.run_id}
                  className="rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {run.suite_id}
                    </p>
                    <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                      {run.run_kind.replaceAll("_", " ")}
                    </span>
                  </div>
                  <div className="mt-2 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                    <span>Score {run.avg_score ?? 0}</span>
                    <span>Pass {run.pass_rate ?? 0}%</span>
                    <span>{run.passed_attempt_count}/{run.attempt_count}</span>
                  </div>
                  <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                    {run.completed_at
                      ? new Date(run.completed_at).toLocaleString()
                      : "Run still in progress"}
                  </p>
                </div>
              ))}
            </div>
          </ChartCard>

          <ChartCard title="Benchmark Model Performance">
            <div className="space-y-3">
              {(benchmarkDashboard?.model_performance ?? []).length > 0 ? (
                benchmarkDashboard?.model_performance.map((model) => (
                  <div
                    key={model.model_id}
                    className="rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-3"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100 break-all">
                        {model.model_id}
                      </p>
                      <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                        {model.attempts} attempts
                      </span>
                    </div>
                    <div className="mt-2 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                      <span>Score {model.avg_score ?? 0}</span>
                      <span>Pass {model.pass_rate}%</span>
                      <span>{model.avg_latency_ms ?? 0} ms</span>
                    </div>
                  </div>
                ))
              ) : (
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  No persisted model benchmark attempts yet.
                </p>
              )}
            </div>
          </ChartCard>
        </div>
      </main>
    </div>
  );
}
