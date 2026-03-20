"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Clock,
  DollarSign,
  FlaskConical,
  Loader2,
  Orbit,
  Radar,
  Sigma,
  Sparkles,
  Trophy,
} from "lucide-react";

import { fetchAgent, fetchAgentBenchmarkDashboard, fetchAgentMetrics } from "@/lib/api";
import { BenchmarkExperimentSection } from "@/app/agents/[slug]/analytics/components/BenchmarkExperimentSection";
import { BenchmarkTrendSection } from "@/app/agents/[slug]/analytics/components/BenchmarkTrendSection";
import { ChartCard } from "@/app/agents/[slug]/analytics/components/ChartCard";
import { ChartSection } from "@/app/agents/[slug]/analytics/components/ChartSection";
import { KPICard } from "@/app/agents/[slug]/analytics/components/KPICard";
import { metricsToAnalytics } from "@/app/agents/[slug]/analytics/utils";
import type {
  AgentBenchmarkCaseSummary,
  AgentBenchmarkDashboard,
  AgentBenchmarkModelSummary,
  AgentBenchmarkRunSummary,
  AgentRegressionClusterSummary,
  AgentBenchmarkSuiteSummary,
} from "@/app/agents/[slug]/analytics/types";
import { ArenaPreviewCard } from "@/app/agents/[slug]/analytics/components/ArenaPreviewCard";

import { ArenaHeader, type ArenaView } from "./ArenaHeader";

type ArenaWindow = 7 | 30 | 90;

interface AgentArenaDashboardProps {
  slug: string;
  backHref?: string;
  initialView?: ArenaView;
}

function formatRelativeTime(iso: string | null | undefined) {
  if (!iso) {
    return "No completed runs yet";
  }
  const value = new Date(iso).getTime();
  if (Number.isNaN(value)) {
    return "Unknown";
  }
  const diffMs = Date.now() - value;
  const diffHours = Math.max(Math.round(diffMs / (1000 * 60 * 60)), 0);
  if (diffHours < 1) {
    return "Less than an hour ago";
  }
  if (diffHours < 24) {
    return `${diffHours}h ago`;
  }
  const diffDays = Math.round(diffHours / 24);
  if (diffDays < 30) {
    return `${diffDays}d ago`;
  }
  return new Date(iso).toLocaleDateString();
}

function formatArenaLabel(value: string | null | undefined) {
  if (!value) {
    return "Unknown";
  }
  return value.replace(/\bjenny\b/gi, "persona");
}

function toSortableTime(iso: string | null | undefined) {
  if (!iso) {
    return 0;
  }
  const value = new Date(iso).getTime();
  return Number.isNaN(value) ? 0 : value;
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "Pending";
  }
  return `${value.toFixed(1)}%`;
}

function formatScore(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "Pending";
  }
  return value.toFixed(1);
}

function deriveArenaStatus(benchmarkDashboard: AgentBenchmarkDashboard) {
  const { avg_score: avgScore, pass_rate: passRate, open_regressions: regressions } =
    benchmarkDashboard.overview;
  if (regressions >= 3 || passRate < 60) {
    return {
      label: "Regression pressure",
      tone:
        "bg-rose-100 text-rose-700 ring-1 ring-rose-200 dark:bg-rose-950/30 dark:text-rose-300 dark:ring-rose-800",
      detail: "Arena is catching active failures that still need reduction before trust increases.",
    };
  }
  if (regressions > 0 || avgScore < 90) {
    return {
      label: "Under watch",
      tone:
        "bg-amber-100 text-amber-700 ring-1 ring-amber-200 dark:bg-amber-950/30 dark:text-amber-300 dark:ring-amber-800",
      detail: "Core behavior is mostly intact, but there are still open weaknesses in the benchmark battery.",
    };
  }
  return {
    label: "Stable",
    tone:
      "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-800",
    detail: "Recent runs are holding their ground with low regression pressure and solid benchmark scores.",
  };
}

function sortModels(models: AgentBenchmarkModelSummary[]) {
  return [...models].sort((a, b) => {
    const scoreDelta = (b.avg_score ?? -1) - (a.avg_score ?? -1);
    if (scoreDelta !== 0) {
      return scoreDelta;
    }
    const passDelta = b.pass_rate - a.pass_rate;
    if (passDelta !== 0) {
      return passDelta;
    }
    return b.attempts - a.attempts;
  });
}

function sortRuns(runs: AgentBenchmarkRunSummary[]) {
  return [...runs].sort((a, b) => {
    const aValue = new Date(a.completed_at ?? a.started_at).getTime();
    const bValue = new Date(b.completed_at ?? b.started_at).getTime();
    return bValue - aValue;
  });
}

function sortRegressions(regressions: AgentRegressionClusterSummary[]) {
  return [...regressions].sort((a, b) => {
    if (b.occurrence_count !== a.occurrence_count) {
      return b.occurrence_count - a.occurrence_count;
    }
    return (b.latest_avg_score ?? 0) - (a.latest_avg_score ?? 0);
  });
}

function sortSuites(suites: AgentBenchmarkSuiteSummary[]) {
  return [...suites].sort((a, b) => {
    if (b.open_regressions !== a.open_regressions) {
      return b.open_regressions - a.open_regressions;
    }
    if ((a.avg_score ?? 999) !== (b.avg_score ?? 999)) {
      return (a.avg_score ?? 999) - (b.avg_score ?? 999);
    }
    if (b.run_count !== a.run_count) {
      return b.run_count - a.run_count;
    }
    return toSortableTime(b.latest_completed_at) - toSortableTime(a.latest_completed_at);
  });
}

function sortCases(cases: AgentBenchmarkCaseSummary[]) {
  return [...cases].sort((a, b) => {
    if (b.open_regressions !== a.open_regressions) {
      return b.open_regressions - a.open_regressions;
    }
    if (a.pass_rate !== b.pass_rate) {
      return a.pass_rate - b.pass_rate;
    }
    if ((a.avg_score ?? 999) !== (b.avg_score ?? 999)) {
      return (a.avg_score ?? 999) - (b.avg_score ?? 999);
    }
    if (b.attempts !== a.attempts) {
      return b.attempts - a.attempts;
    }
    return toSortableTime(b.latest_completed_at) - toSortableTime(a.latest_completed_at);
  });
}

export function AgentArenaDashboard({
  slug,
  backHref,
  initialView = "overview",
}: AgentArenaDashboardProps) {
  const [windowDays, setWindowDays] = useState<ArenaWindow>(30);
  const [activeView, setActiveView] = useState<ArenaView>(initialView);

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
    isLoading: benchmarkLoading,
    error: benchmarkError,
    refetch: refetchBenchmarks,
    isRefetching: benchmarksRefetching,
  } = useQuery({
    queryKey: ["agent-benchmarks", slug, windowDays],
    queryFn: () => fetchAgentBenchmarkDashboard(slug, windowDays, 24),
    enabled: !!slug,
  });

  const isLoading = agentLoading || metricsLoading || benchmarkLoading;
  const error = agentError;
  const isRefreshing = agentRefetching || metricsRefetching || benchmarksRefetching;
  const analytics = agent && metrics ? metricsToAnalytics(metrics, agent) : null;
  const benchmarkErrorMessage = benchmarkError instanceof Error ? benchmarkError.message : null;
  const runtimeErrorMessage = metricsError instanceof Error ? metricsError.message : null;

  const status = useMemo(
    () => (benchmarkDashboard ? deriveArenaStatus(benchmarkDashboard) : null),
    [benchmarkDashboard],
  );
  const sortedModels = useMemo(
    () => sortModels(benchmarkDashboard?.model_performance ?? []).slice(0, 5),
    [benchmarkDashboard],
  );
  const sortedSuites = useMemo(
    () => sortSuites(benchmarkDashboard?.suites ?? []).slice(0, 8),
    [benchmarkDashboard],
  );
  const sortedCases = useMemo(
    () => sortCases(benchmarkDashboard?.cases ?? []).slice(0, 10),
    [benchmarkDashboard],
  );
  const recentRuns = useMemo(
    () => sortRuns(benchmarkDashboard?.recent_runs ?? []).slice(0, 6),
    [benchmarkDashboard],
  );
  const regressions = useMemo(
    () => sortRegressions(benchmarkDashboard?.open_regressions ?? []).slice(0, 6),
    [benchmarkDashboard],
  );
  const trackedSuiteCount = useMemo(
    () => benchmarkDashboard?.suites.length ?? 0,
    [benchmarkDashboard],
  );
  const pressuredCaseCount = useMemo(
    () => sortedCases.filter((summary) => summary.open_regressions > 0).length,
    [sortedCases],
  );
  const primaryModel = agent?.primary_model_id ?? null;
  const bestModel = sortedModels[0] ?? null;
  const hasHistory = (benchmarkDashboard?.overview.total_runs ?? 0) > 0;
  const hasRuntimeActivity = analytics
    ? analytics.totalRequests > 0 || analytics.totalTokens > 0 || analytics.totalCostUsd > 0
    : false;

  function handleRefresh() {
    void Promise.all([refetchAgent(), refetchMetrics(), refetchBenchmarks()]);
  }

  function renderRuntimePanels() {
    if (runtimeErrorMessage || !analytics) {
      return (
        <div className="mt-6">
          <ChartCard title="Runtime view">
            <div className="rounded-2xl border border-dashed border-amber-300 bg-amber-50 px-6 py-10 text-center dark:border-amber-900 dark:bg-amber-950/20">
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                Runtime metrics unavailable
              </p>
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                {runtimeErrorMessage ?? "No runtime metrics are available for this agent yet."}
              </p>
            </div>
          </ChartCard>
        </div>
      );
    }

    return (
      <>
        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <KPICard
            label="24h Cost"
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

        <div className="mt-6">
          {hasRuntimeActivity ? (
            <ChartSection trend={analytics.trend} />
          ) : (
            <ChartCard title="Activity window">
              <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-6 py-10 text-center dark:border-slate-700 dark:bg-slate-900/40">
                <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
                  No recent runtime activity
                </p>
                <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                  This agent has not handled any requests in the last 24 hours yet.
                </p>
              </div>
            </ChartCard>
          )}
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
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

          <ChartCard title="Model routing">
            <div className="space-y-2">
              {analytics.modelSummary.map((model) => (
                <div
                  key={model}
                  className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700"
                >
                  <span className="break-all text-slate-600 dark:text-slate-300">
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
                <span className="text-slate-500 dark:text-slate-400">Metrics basis</span>
                <span className="font-semibold text-slate-900 dark:text-slate-100">
                  24h aggregate
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500 dark:text-slate-400">Agent updated</span>
                <span className="font-semibold text-slate-900 dark:text-slate-100">
                  {new Date(analytics.lastUpdatedAt).toLocaleString()}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500 dark:text-slate-400">Primary model</span>
                <span className="font-semibold text-slate-900 dark:text-slate-100">
                  {primaryModel ?? "Unassigned"}
                </span>
              </div>
            </div>
          </ChartCard>
        </div>
      </>
    );
  }

  function renderRecentRunsCard(title = "Recent runs") {
    return (
      <ChartCard title={title}>
        {recentRuns.length === 0 ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">No persisted runs yet.</p>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {recentRuns.map((run) => (
              <article
                key={run.run_id}
                className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 dark:border-slate-800 dark:bg-slate-950/50"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        {formatArenaLabel(run.suite_id)}
                      </p>
                    <p className="mt-1 text-xs uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                      {run.run_kind}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-lg font-semibold text-slate-950 dark:text-slate-50">
                      {formatScore(run.avg_score)}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {formatPercent(run.pass_rate)}
                    </p>
                  </div>
                </div>

                <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                      Attempts
                    </dt>
                    <dd className="mt-1 font-medium text-slate-900 dark:text-slate-100">
                      {run.passed_attempt_count}/{run.attempt_count}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                      Infra failures
                    </dt>
                    <dd className="mt-1 font-medium text-slate-900 dark:text-slate-100">
                      {run.infra_failure_count}
                    </dd>
                  </div>
                </dl>

                <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
                  Models: {run.models.join(", ")}
                </p>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  Cases: {run.case_ids.join(", ")}
                </p>
              </article>
            ))}
          </div>
        )}
      </ChartCard>
    );
  }

  function renderRegressionWatchlist() {
    return (
      <ChartCard title="Regression watchlist">
        {regressions.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-emerald-200 bg-emerald-50 px-5 py-8 text-center dark:border-emerald-900 dark:bg-emerald-950/20">
            <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              No open regression clusters
            </p>
            <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
              Arena is currently tracking clean recent benchmark history for this agent.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {regressions.map((regression) => (
              <article
                key={regression.regression_key}
                className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 dark:border-rose-900 dark:bg-rose-950/20"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {regression.case_id}
                    </p>
                    <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                      {regression.failure_detail}
                    </p>
                  </div>
                  <span className="rounded-full bg-white px-2 py-1 text-[11px] font-semibold text-rose-700 ring-1 ring-rose-200 dark:bg-slate-900 dark:text-rose-300 dark:ring-rose-900">
                    {regression.occurrence_count} hits
                  </span>
                </div>
                <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                  {formatArenaLabel(regression.suite_id)} · models {regression.affected_models.join(", ")}
                </p>
              </article>
            ))}
          </div>
        )}
      </ChartCard>
    );
  }

  function renderSuitePanels() {
    return (
      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <ChartCard title="Suite board">
          {sortedSuites.length === 0 ? (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              No suite history yet. Arena needs a benchmark battery before it can score stability by suite.
            </p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {sortedSuites.map((suite) => {
                const tone =
                  suite.open_regressions > 0 || (suite.avg_score ?? 100) < 90
                    ? "border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/20"
                    : "border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/20";
                const badgeTone =
                  suite.open_regressions > 0
                    ? "bg-rose-100 text-rose-700 ring-rose-200 dark:bg-rose-950/30 dark:text-rose-300 dark:ring-rose-900"
                    : "bg-emerald-100 text-emerald-700 ring-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-900";

                return (
                  <article
                    key={suite.suite_id}
                    className={`rounded-2xl border px-4 py-4 ${tone}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                          {formatArenaLabel(suite.suite_id)}
                        </p>
                        <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                          {suite.run_count} runs · {suite.case_ids.length} cases ·{" "}
                          {suite.run_kinds.join(", ") || "benchmark"}
                        </p>
                      </div>
                      <span
                        className={`rounded-full px-2 py-1 text-[11px] font-semibold ring-1 ${badgeTone}`}
                      >
                        {suite.open_regressions > 0
                          ? `${suite.open_regressions} regressions`
                          : "stable"}
                      </span>
                    </div>

                    <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
                      <div>
                        <dt className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                          Score
                        </dt>
                        <dd className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
                          {formatScore(suite.avg_score)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                          Pass rate
                        </dt>
                        <dd className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
                          {formatPercent(suite.pass_rate)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                          Last run
                        </dt>
                        <dd className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
                          {formatRelativeTime(suite.latest_completed_at)}
                        </dd>
                      </div>
                    </dl>

                    <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
                      Models: {suite.tracked_models.join(", ") || "Pending"}
                    </p>
                  </article>
                );
              })}
            </div>
          )}
        </ChartCard>

        <ChartCard title="Case watchlist">
          {sortedCases.length === 0 ? (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              No case-level evidence yet. Once attempts are persisted, Arena will rank brittle cases here.
            </p>
          ) : (
            <div className="space-y-3">
              {sortedCases.map((caseSummary) => (
                <article
                  key={caseSummary.case_id}
                  className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/50"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        {caseSummary.case_id}
                      </p>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        {caseSummary.suite_ids.map((suiteId) => formatArenaLabel(suiteId)).join(", ")} · {caseSummary.attempts} attempts
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-semibold text-slate-950 dark:text-slate-50">
                        {formatScore(caseSummary.avg_score)}
                      </p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        {formatPercent(caseSummary.pass_rate)}
                      </p>
                    </div>
                  </div>

                  {caseSummary.latest_failure_detail ? (
                    <p className="mt-3 text-xs text-slate-600 dark:text-slate-300">
                      {caseSummary.latest_failure_detail}
                    </p>
                  ) : null}

                  <div className="mt-3 flex flex-wrap gap-2 text-[11px] font-medium">
                    <span className="rounded-full bg-slate-100 px-2 py-1 text-slate-700 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700">
                      {caseSummary.open_regressions} open regressions
                    </span>
                    <span className="rounded-full bg-slate-100 px-2 py-1 text-slate-700 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700">
                      {formatRelativeTime(caseSummary.latest_completed_at)}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </ChartCard>
      </div>
    );
  }

  function renderOverviewPanels() {
    if (!benchmarkDashboard) {
      return (
        <>
          <div className="mt-6">
            <ChartCard title="Arena evidence">
              <div className="rounded-2xl border border-dashed border-amber-300 bg-amber-50 px-6 py-10 text-center dark:border-amber-900 dark:bg-amber-950/20">
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  Arena benchmark history unavailable
                </p>
                <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                  {benchmarkErrorMessage ?? "No benchmark history is available for this agent yet."}
                </p>
              </div>
            </ChartCard>
          </div>
          {renderRuntimePanels()}
        </>
      );
    }

    if (!hasHistory) {
      return (
        <>
          <div className="mt-6">
            <ArenaPreviewCard
              dashboard={benchmarkDashboard}
              slug={slug}
              ctaLabel={null}
              compact={false}
            />
          </div>
          {renderRuntimePanels()}
        </>
      );
    }

    return (
      <>
        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <KPICard
            label="Benchmark Runs"
            value={benchmarkDashboard.overview.total_runs}
            icon={FlaskConical}
            color="blue"
          />
          <KPICard
            label="Average Score"
            value={formatScore(benchmarkDashboard.overview.avg_score)}
            icon={Trophy}
            color="green"
          />
          <KPICard
            label="Pass Rate"
            value={formatPercent(benchmarkDashboard.overview.pass_rate)}
            icon={Activity}
            color="amber"
          />
          <KPICard
            label="Open Regressions"
            value={benchmarkDashboard.overview.open_regressions}
            icon={AlertTriangle}
            color="red"
          />
        </div>

        <div className="mt-6">
          <BenchmarkTrendSection trend={benchmarkDashboard.trend} />
        </div>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.15fr_0.85fr]">
          <ChartCard title="Model leaderboard">
            {sortedModels.length === 0 ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">No model data yet.</p>
            ) : (
              <div className="space-y-3">
                {sortedModels.map((model, index) => (
                  <article
                    key={model.model_id}
                    className="flex items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/50"
                  >
                    <div className="min-w-0">
                      <p className="text-xs uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                        Rank {index + 1}
                      </p>
                      <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                        {model.model_id}
                      </p>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                        {model.attempts} attempts · last seen {formatRelativeTime(model.latest_completed_at)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-lg font-semibold text-slate-950 dark:text-slate-50">
                        {formatScore(model.avg_score)}
                      </p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        pass {formatPercent(model.pass_rate)}
                      </p>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </ChartCard>

          {renderRegressionWatchlist()}
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[0.9fr_1.1fr]">
          <ChartCard title="Runtime pulse">
            {runtimeErrorMessage || !analytics ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {runtimeErrorMessage ?? "Runtime metrics are unavailable."}
              </p>
            ) : (
              <div className="space-y-4">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-500 dark:text-slate-400">Requests</span>
                  <span className="font-semibold text-slate-900 dark:text-slate-100">
                    {analytics.totalRequests}
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-500 dark:text-slate-400">Success rate</span>
                  <span className="font-semibold text-slate-900 dark:text-slate-100">
                    {analytics.successRate}%
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-500 dark:text-slate-400">Average latency</span>
                  <span className="font-semibold text-slate-900 dark:text-slate-100">
                    {analytics.avgLatencyMs} ms
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-500 dark:text-slate-400">Primary model</span>
                  <span className="font-semibold text-slate-900 dark:text-slate-100">
                    {primaryModel ?? "Unassigned"}
                  </span>
                </div>
              </div>
            )}
          </ChartCard>

          {renderRecentRunsCard()}
        </div>

        {renderSuitePanels()}
      </>
    );
  }

  function renderExperimentPanels() {
    if (!benchmarkDashboard) {
      return (
        <div className="mt-6">
          <ChartCard title="Experiments">
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {benchmarkErrorMessage ?? "No benchmark experiments are available."}
            </p>
          </ChartCard>
        </div>
      );
    }

    return (
      <>
        <div className="mt-6">
          {benchmarkDashboard.experiments.length > 0 ? (
            <BenchmarkExperimentSection experiments={benchmarkDashboard.experiments} />
          ) : (
            <ChartCard title="Experiments">
              <p className="text-sm text-slate-500 dark:text-slate-400">
                No persisted experiments yet. Arena will surface cohort comparisons here once runs are being promoted or held.
              </p>
            </ChartCard>
          )}
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[1.1fr_0.9fr]">
          {renderRecentRunsCard("Recent experimental runs")}
          {renderRegressionWatchlist()}
        </div>
      </>
    );
  }

  function renderActivePanels() {
    if (activeView === "runtime") {
      return renderRuntimePanels();
    }
    if (activeView === "experiments") {
      return renderExperimentPanels();
    }
    if (activeView === "suites") {
      return renderSuitePanels();
    }
    return renderOverviewPanels();
  }

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[linear-gradient(180deg,#f8fafc_0%,#eef6ff_100%)] dark:bg-slate-950">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    );
  }

  if (error) {
    const errorMessage = error instanceof Error ? error.message : "Failed to load Arena";
    return (
      <div className="min-h-screen flex items-center justify-center bg-[linear-gradient(180deg,#f8fafc_0%,#eef6ff_100%)] px-6 dark:bg-slate-950">
        <div className="max-w-md rounded-3xl border border-rose-200 bg-white/90 p-8 text-center shadow-sm dark:border-rose-900 dark:bg-slate-900/90">
          <AlertCircle className="mx-auto mb-3 h-10 w-10 text-rose-500" />
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Arena unavailable
          </p>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">{errorMessage}</p>
        </div>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[linear-gradient(180deg,#f8fafc_0%,#eef6ff_100%)] dark:bg-slate-950">
        <div className="text-center">
          <AlertCircle className="mx-auto mb-3 h-10 w-10 text-rose-500" />
          <p className="text-sm text-slate-600 dark:text-slate-400">Agent not found</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[linear-gradient(180deg,#f8fafc_0%,#eef6ff_30%,#f8fafc_100%)] dark:bg-slate-950">
      <ArenaHeader
        agentName={agent.name}
        slug={slug}
        backHref={backHref}
        windowDays={windowDays}
        activeView={activeView}
        onWindowDaysChange={setWindowDays}
        onViewChange={setActiveView}
        onRefresh={handleRefresh}
        isRefreshing={isRefreshing}
      />

      <main className="mx-auto max-w-7xl p-6 lg:p-8">
        <section className="relative overflow-hidden rounded-[28px] border border-cyan-200/70 bg-white/90 p-6 shadow-sm dark:border-cyan-900/40 dark:bg-slate-900/90 lg:p-8">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.14),transparent_38%),radial-gradient(circle_at_bottom_right,rgba(16,185,129,0.12),transparent_34%)]" />
          <div className="pointer-events-none absolute inset-0 opacity-40 [background-image:linear-gradient(to_right,rgba(148,163,184,0.16)_1px,transparent_1px),linear-gradient(to_bottom,rgba(148,163,184,0.16)_1px,transparent_1px)] [background-size:28px_28px]" />

          <div className="relative flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-200 dark:bg-cyan-950/60 dark:text-cyan-100">
                <FlaskConical className="h-3.5 w-3.5" />
                Arena
              </div>
              <h1 className="mt-4 text-3xl font-semibold tracking-tight text-slate-950 dark:text-slate-50 lg:text-4xl">
                Benchmark the agent, not the story about the agent.
              </h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">
                Arena turns benchmark history into a readable field report: stability, runtime health,
                controlled experiments, and the regressions still shaping trust.
              </p>

              <div className="mt-5 flex flex-wrap gap-2">
                <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${status?.tone ?? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200"}`}>
                  <Radar className="h-3.5 w-3.5" />
                  {status?.label ?? "Collecting evidence"}
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 ring-1 ring-slate-200 dark:bg-slate-800/80 dark:text-slate-200 dark:ring-slate-700">
                  <Orbit className="h-3.5 w-3.5" />
                  {benchmarkDashboard?.overview.tracked_models.length ?? 0} tracked models
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 ring-1 ring-slate-200 dark:bg-slate-800/80 dark:text-slate-200 dark:ring-slate-700">
                  <Activity className="h-3.5 w-3.5" />
                  {trackedSuiteCount} active suites
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 ring-1 ring-slate-200 dark:bg-slate-800/80 dark:text-slate-200 dark:ring-slate-700">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  {pressuredCaseCount} pressured cases
                </span>
              </div>
            </div>

            <div className="relative grid gap-3 rounded-2xl border border-slate-200/80 bg-slate-50/90 p-4 dark:border-slate-800 dark:bg-slate-950/60 xl:w-[360px]">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                    Field status
                  </p>
                  <p className="mt-2 text-sm text-slate-700 dark:text-slate-200">
                    {status?.detail ?? "Arena is waiting for benchmark evidence before it can judge stability or regression pressure."}
                  </p>
                </div>
                <Sparkles className="h-5 w-5 text-cyan-500" />
              </div>

              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl bg-white px-3 py-2 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
                  <dt className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    Last run
                  </dt>
                  <dd className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
                    {formatRelativeTime(benchmarkDashboard?.overview.latest_completed_at)}
                  </dd>
                </div>
                <div className="rounded-xl bg-white px-3 py-2 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
                  <dt className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    Best model
                  </dt>
                  <dd className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
                    {bestModel?.model_id ?? primaryModel ?? "Pending"}
                  </dd>
                </div>
              </dl>
            </div>
          </div>
        </section>

        {renderActivePanels()}

        <div className="mt-6">
          <ChartCard title="Arena loop">
            <div className="flex flex-col gap-3 text-sm text-slate-600 dark:text-slate-300 lg:flex-row lg:items-center lg:justify-between">
              <p className="max-w-3xl">
                Arena is where benchmark suites, experiments, regressions, and runtime evidence stay visible enough to guide real prompt, harness, and model decisions instead of anecdotal tuning.
              </p>
              <button
                type="button"
                onClick={() =>
                  setActiveView(activeView === "runtime" ? "overview" : "runtime")
                }
                className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-800 dark:bg-cyan-600 dark:hover:bg-cyan-500"
              >
                {activeView === "runtime" ? "Return to overview" : "View runtime lens"}
              </button>
            </div>
          </ChartCard>
        </div>
      </main>
    </div>
  );
}
