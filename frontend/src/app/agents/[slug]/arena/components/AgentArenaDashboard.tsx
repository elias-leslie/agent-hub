"use client";

import { useCallback, useMemo, useState } from "react";
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

import { fetchAgent, fetchAgentBenchmarkDashboard, fetchAgentBenchmarkRunDetail, fetchAgentMetrics } from "@/lib/api";
import { BenchmarkExperimentSection } from "@/app/agents/[slug]/analytics/components/BenchmarkExperimentSection";
import { BenchmarkTrendSection } from "@/app/agents/[slug]/analytics/components/BenchmarkTrendSection";
import { ChartCard } from "@/app/agents/[slug]/analytics/components/ChartCard";
import { ChartSection } from "@/app/agents/[slug]/analytics/components/ChartSection";
import { KPICard } from "@/app/agents/[slug]/analytics/components/KPICard";
import { metricsToAnalytics } from "@/app/agents/[slug]/analytics/utils";
import type {
  AgentBenchmarkAttemptDetail,
  AgentBenchmarkCaseSummary,
  AgentBenchmarkDashboard,
  AgentBenchmarkModelSummary,
  AgentBenchmarkRunDetail,
  AgentBenchmarkRunSummary,
  AgentRegressionClusterSummary,
  AgentBenchmarkSuiteSummary,
} from "@/app/agents/[slug]/analytics/types";
import { ArenaPreviewCard } from "@/app/agents/[slug]/analytics/components/ArenaPreviewCard";
import {
  deriveArenaStatus,
  formatArenaLabel,
  formatPercent,
  formatRelativeTime,
  formatScore,
} from "@/app/arena/utils";

import { ArenaHeader, type ArenaView } from "./ArenaHeader";

type ArenaWindow = 7 | 30 | 90;

interface AgentArenaDashboardProps {
  slug: string;
  backHref?: string;
  initialView?: ArenaView;
}

function toSortableTime(iso: string | null | undefined) {
  if (!iso) {
    return 0;
  }
  const value = new Date(iso).getTime();
  return Number.isNaN(value) ? 0 : value;
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

function SkeletonBlock({ className }: { className: string }) {
  return <div className={`rounded bg-slate-800 animate-shimmer ${className}`} />;
}

function LoadingSkeleton() {
  return (
    <div className="min-h-screen bg-slate-950">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />
      <div className="sticky top-0 z-30 border-b border-slate-800 bg-slate-900/95 backdrop-blur-sm">
        <div className="px-6 lg:px-8 py-3">
          <div className="flex items-center gap-4">
            <SkeletonBlock className="h-8 w-8" />
            <SkeletonBlock className="h-5 w-40" />
            <SkeletonBlock className="h-5 w-16" />
          </div>
          <div className="mt-3 flex gap-1">
            <SkeletonBlock className="h-8 w-20" />
            <SkeletonBlock className="h-8 w-16" />
            <SkeletonBlock className="h-8 w-20" />
            <SkeletonBlock className="h-8 w-28" />
          </div>
        </div>
      </div>
      <main className="relative mx-auto max-w-7xl p-6 lg:p-8">
        <div className="rounded-[20px] border border-slate-800 bg-slate-900/60 p-6 lg:p-8">
          <SkeletonBlock className="h-5 w-24" />
          <SkeletonBlock className="mt-4 h-10 w-[28rem]" />
          <SkeletonBlock className="mt-3 h-4 w-96" />
          <div className="mt-5 flex gap-2">
            <SkeletonBlock className="h-7 w-28" />
            <SkeletonBlock className="h-7 w-36" />
          </div>
        </div>
        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
              <SkeletonBlock className="h-3 w-24" />
              <SkeletonBlock className="mt-3 h-7 w-16" />
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

export function AgentArenaDashboard({
  slug,
  backHref,
  initialView = "overview",
}: AgentArenaDashboardProps) {
  const [windowDays, setWindowDays] = useState<ArenaWindow>(30);
  const [activeView, setActiveView] = useState<ArenaView>(initialView);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<AgentBenchmarkRunDetail | null>(null);
  const [runDetailLoading, setRunDetailLoading] = useState(false);

  const handleRunClick = useCallback(
    async (runId: string) => {
      if (expandedRunId === runId) {
        setExpandedRunId(null);
        setRunDetail(null);
        return;
      }
      setExpandedRunId(runId);
      setRunDetail(null);
      setRunDetailLoading(true);
      try {
        const detail = await fetchAgentBenchmarkRunDetail(slug, runId);
        setRunDetail(detail);
      } catch {
        setRunDetail(null);
      } finally {
        setRunDetailLoading(false);
      }
    },
    [expandedRunId, slug],
  );

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
            <div className="rounded-2xl border border-dashed border-amber-900 bg-amber-950/20 px-6 py-10 text-center">
              <p className="text-sm font-semibold text-slate-100">
                Runtime metrics unavailable
              </p>
              <p className="mt-2 text-sm text-slate-400">
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
              <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/40 px-6 py-10 text-center">
                <p className="text-sm font-medium text-slate-100">
                  No recent runtime activity
                </p>
                <p className="mt-2 text-sm text-slate-400">
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
                <span className="text-slate-400">Requests</span>
                <span className="font-semibold text-slate-100">
                  {analytics.totalRequests}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-400">Requests / hour</span>
                <span className="font-semibold text-slate-100">
                  {analytics.requestsPerHour}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-400">Tokens</span>
                <span className="font-semibold text-slate-100">
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
                  className="flex items-center justify-between rounded-lg border border-slate-700 px-3 py-2 text-sm"
                >
                  <span className="break-all text-slate-300">
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
                <span className="text-slate-400">Metrics basis</span>
                <span className="font-semibold text-slate-100">
                  24h aggregate
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Agent updated</span>
                <span className="font-semibold text-slate-100">
                  {new Date(analytics.lastUpdatedAt).toLocaleString()}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Primary model</span>
                <span className="font-semibold text-slate-100">
                  {primaryModel ?? "Unassigned"}
                </span>
              </div>
            </div>
          </ChartCard>
        </div>
      </>
    );
  }

  function renderAttemptRow(attempt: AgentBenchmarkAttemptDetail) {
    return (
      <div
        key={attempt.id}
        className={`flex items-center gap-3 rounded-xl px-3 py-2 text-sm ${attempt.passed ? "bg-emerald-950/20" : "bg-rose-950/20"}`}
      >
        <span className={`h-2 w-2 rounded-full ${attempt.passed ? "bg-emerald-500" : "bg-rose-500"}`} />
        <span className="min-w-0 flex-1 truncate font-medium text-slate-100">
          {attempt.case_name ?? attempt.case_id}
        </span>
        <span className="shrink-0 text-xs text-slate-400">
          {attempt.model_id}
        </span>
        <span className="shrink-0 w-12 text-right font-semibold text-slate-100">
          {attempt.composite_score.toFixed(0)}
        </span>
        <span className="shrink-0 w-16 text-right text-xs text-slate-400">
          {attempt.latency_ms}ms
        </span>
      </div>
    );
  }

  function renderRunDrillDown() {
    if (!expandedRunId) return null;
    if (runDetailLoading) {
      return (
        <div className="mt-3 flex items-center justify-center py-4">
          <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
        </div>
      );
    }
    if (!runDetail) return null;

    const failedAttempts = runDetail.attempts.filter((a) => !a.passed);
    const passedAttempts = runDetail.attempts.filter((a) => a.passed);

    return (
      <div className="mt-3 space-y-1.5">
        {failedAttempts.length > 0 ? (
          <>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-rose-400">
              Failed ({failedAttempts.length})
            </p>
            {failedAttempts.map((attempt) => (
              <div key={attempt.id}>
                {renderAttemptRow(attempt)}
                {attempt.failure_detail ? (
                  <p className="ml-5 mt-1 text-[11px] text-rose-400">
                    {attempt.failure_detail}
                  </p>
                ) : null}
              </div>
            ))}
          </>
        ) : null}
        {passedAttempts.length > 0 ? (
          <>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-emerald-400">
              Passed ({passedAttempts.length})
            </p>
            {passedAttempts.map(renderAttemptRow)}
          </>
        ) : null}
      </div>
    );
  }

  function renderRecentRunsCard(title = "Recent runs") {
    return (
      <ChartCard title={title}>
        {recentRuns.length === 0 ? (
          <p className="text-sm text-slate-400">No persisted runs yet.</p>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {recentRuns.map((run) => {
              const isExpanded = expandedRunId === run.run_id;
              return (
              <article
                key={run.run_id}
                role="button"
                tabIndex={0}
                onClick={() => void handleRunClick(run.run_id)}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") void handleRunClick(run.run_id); }}
                aria-expanded={isExpanded}
                className={`cursor-pointer rounded-2xl border px-4 py-4 transition-colors ${isExpanded ? "border-amber-800 bg-amber-950/20" : "border-slate-800 bg-slate-950/50 hover:border-slate-700"}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                      <p className="text-sm font-semibold text-slate-100">
                        {formatArenaLabel(run.suite_id)}
                      </p>
                    <p className="mt-1 text-xs uppercase tracking-[0.16em] text-slate-400">
                      {run.run_kind}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-lg font-semibold text-slate-50">
                      {formatScore(run.avg_score)}
                    </p>
                    <p className="text-xs text-slate-400">
                      {formatPercent(run.pass_rate)}
                    </p>
                  </div>
                </div>

                <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-slate-400">
                      Attempts
                    </dt>
                    <dd className="mt-1 font-medium text-slate-100">
                      {run.passed_attempt_count}/{run.attempt_count}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-slate-400">
                      Infra failures
                    </dt>
                    <dd className="mt-1 font-medium text-slate-100">
                      {run.infra_failure_count}
                    </dd>
                  </div>
                </dl>

                <p className="mt-4 text-xs text-slate-400">
                  Models: {run.models.join(", ")}
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  Cases: {run.case_ids.join(", ")}
                </p>

                {isExpanded ? renderRunDrillDown() : null}
              </article>
              );
            })}
          </div>
        )}
      </ChartCard>
    );
  }

  function renderRegressionWatchlist() {
    return (
      <ChartCard title="Regression watchlist">
        {regressions.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-emerald-900 bg-emerald-950/20 px-5 py-8 text-center">
            <p className="text-sm font-semibold text-slate-100">
              No open regression clusters
            </p>
            <p className="mt-2 text-sm text-slate-400">
              Arena is currently tracking clean recent benchmark history for this agent.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {regressions.map((regression) => (
              <article
                key={regression.regression_key}
                className="rounded-2xl border border-rose-900 bg-rose-950/20 px-4 py-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-100">
                      {regression.case_id}
                    </p>
                    <p className="mt-1 text-xs text-slate-300">
                      {regression.failure_detail}
                    </p>
                  </div>
                  <span className="rounded-full bg-slate-900 px-2 py-1 text-[11px] font-semibold text-rose-300 ring-1 ring-rose-900">
                    {regression.occurrence_count} hits
                  </span>
                </div>
                <p className="mt-3 text-xs text-slate-400">
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
            <p className="text-sm text-slate-400">
              No suite history yet. Arena needs a benchmark battery before it can score stability by suite.
            </p>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {sortedSuites.map((suite) => {
                const hasIssues = suite.open_regressions > 0 || (suite.avg_score ?? 100) < 90;
                const tone = hasIssues
                  ? "border-amber-900 bg-amber-950/20"
                  : "border-emerald-900 bg-emerald-950/20";
                const badgeTone = suite.open_regressions > 0
                  ? "bg-rose-950/30 text-rose-300 ring-rose-900"
                  : "bg-emerald-950/30 text-emerald-300 ring-emerald-900";

                return (
                  <article
                    key={suite.suite_id}
                    className={`rounded-2xl border px-4 py-4 ${tone}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-slate-100">
                          {formatArenaLabel(suite.suite_id)}
                        </p>
                        <p className="mt-1 text-xs text-slate-300">
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
                        <dt className="text-xs uppercase tracking-wide text-slate-400">
                          Score
                        </dt>
                        <dd className="mt-1 font-semibold text-slate-100">
                          {formatScore(suite.avg_score)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs uppercase tracking-wide text-slate-400">
                          Pass rate
                        </dt>
                        <dd className="mt-1 font-semibold text-slate-100">
                          {formatPercent(suite.pass_rate)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs uppercase tracking-wide text-slate-400">
                          Last run
                        </dt>
                        <dd className="mt-1 font-semibold text-slate-100">
                          {formatRelativeTime(suite.latest_completed_at)}
                        </dd>
                      </div>
                    </dl>

                    <p className="mt-4 text-xs text-slate-400">
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
            <p className="text-sm text-slate-400">
              No case-level evidence yet. Once attempts are persisted, Arena will rank brittle cases here.
            </p>
          ) : (
            <div className="space-y-3">
              {sortedCases.map((caseSummary) => (
                <article
                  key={caseSummary.case_id}
                  className="rounded-2xl border border-slate-800 bg-slate-950/50 px-4 py-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-slate-100">
                        {caseSummary.case_name ?? caseSummary.case_id}
                      </p>
                      {caseSummary.case_name ? (
                        <p className="mt-0.5 text-[11px] font-mono text-slate-500">
                          {caseSummary.case_id}
                        </p>
                      ) : null}
                      <p className="mt-1 text-xs text-slate-400">
                        {caseSummary.suite_ids.map((suiteId) => formatArenaLabel(suiteId)).join(", ")} · {caseSummary.attempts} attempts
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-semibold text-slate-50">
                        {formatScore(caseSummary.avg_score)}
                      </p>
                      <p className="text-xs text-slate-400">
                        {formatPercent(caseSummary.pass_rate)}
                      </p>
                    </div>
                  </div>

                  {caseSummary.latest_failure_detail ? (
                    <p className="mt-3 text-xs text-slate-300">
                      {caseSummary.latest_failure_detail}
                    </p>
                  ) : null}

                  <div className="mt-3 flex flex-wrap gap-2 text-[11px] font-medium">
                    <span className="rounded-full bg-slate-800 px-2 py-1 text-slate-200 ring-1 ring-slate-700">
                      {caseSummary.open_regressions} open regressions
                    </span>
                    <span className="rounded-full bg-slate-800 px-2 py-1 text-slate-200 ring-1 ring-slate-700">
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
              <div className="rounded-2xl border border-dashed border-amber-900 bg-amber-950/20 px-6 py-10 text-center">
                <p className="text-sm font-semibold text-slate-100">
                  Arena benchmark history unavailable
                </p>
                <p className="mt-2 text-sm text-slate-400">
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
              <p className="text-sm text-slate-400">No model data yet.</p>
            ) : (
              <div className="space-y-3">
                {sortedModels.map((model, index) => {
                  const isPrimary = model.model_id === primaryModel;
                  return (
                  <article
                    key={model.model_id}
                    className={`flex items-center justify-between gap-4 rounded-2xl border px-4 py-3 ${isPrimary ? "border-amber-900 bg-amber-950/20" : "border-slate-800 bg-slate-950/50"}`}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-xs uppercase tracking-[0.16em] text-slate-400">
                          Rank {index + 1}
                        </p>
                        {isPrimary ? (
                          <span className="rounded-full bg-amber-950/40 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300 ring-1 ring-amber-800">
                            primary
                          </span>
                        ) : null}
                      </div>
                      <p className="truncate text-sm font-semibold text-slate-100">
                        {model.model_id}
                      </p>
                      <p className="mt-1 text-xs text-slate-400">
                        {model.attempts} attempts · last seen {formatRelativeTime(model.latest_completed_at)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-lg font-semibold text-slate-50">
                        {formatScore(model.avg_score)}
                      </p>
                      <p className="text-xs text-slate-400">
                        pass {formatPercent(model.pass_rate)}
                      </p>
                    </div>
                  </article>
                  );
                })}
              </div>
            )}
          </ChartCard>

          {renderRegressionWatchlist()}
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[0.9fr_1.1fr]">
          <ChartCard title="Runtime pulse">
            {runtimeErrorMessage || !analytics ? (
              <p className="text-sm text-slate-400">
                {runtimeErrorMessage ?? "Runtime metrics are unavailable."}
              </p>
            ) : (
              <div className="space-y-4">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-400">Requests</span>
                  <span className="font-semibold text-slate-100">
                    {analytics.totalRequests}
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-400">Success rate</span>
                  <span className="font-semibold text-slate-100">
                    {analytics.successRate}%
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-400">Average latency</span>
                  <span className="font-semibold text-slate-100">
                    {analytics.avgLatencyMs} ms
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-400">Primary model</span>
                  <span className="font-semibold text-slate-100">
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
            <p className="text-sm text-slate-400">
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
              <p className="text-sm text-slate-400">
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
    return <LoadingSkeleton />;
  }

  if (error) {
    const errorMessage = error instanceof Error ? error.message : "Failed to load Arena";
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center px-6">
        <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />
        <div className="relative max-w-md rounded-2xl border border-rose-900 bg-slate-900/90 p-8 text-center">
          <AlertCircle className="mx-auto mb-3 h-10 w-10 text-rose-500" />
          <p className="text-sm font-semibold text-slate-100">
            Arena unavailable
          </p>
          <p className="mt-2 text-sm text-slate-400">{errorMessage}</p>
        </div>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />
        <div className="relative text-center">
          <AlertCircle className="mx-auto mb-3 h-10 w-10 text-rose-500" />
          <p className="text-sm text-slate-400">Agent not found</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

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

      <main className="relative mx-auto max-w-7xl p-6 lg:p-8">
        <section className="relative overflow-hidden rounded-[20px] border border-slate-800 bg-slate-900/60 p-6 backdrop-blur-sm lg:p-8">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,oklch(0.75_0.18_55_/_0.08),transparent_38%),radial-gradient(circle_at_bottom_right,oklch(0.7_0.17_155_/_0.06),transparent_34%)]" />

          <div className="relative flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full bg-amber-950/60 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-amber-200">
                <FlaskConical className="h-3.5 w-3.5" />
                Arena
              </div>
              <h1 className="mt-4 text-3xl font-semibold tracking-tight text-slate-50 lg:text-4xl">
                Benchmark the agent, not the story about the agent.
              </h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
                Arena turns benchmark history into a readable field report: stability, runtime health,
                controlled experiments, and the regressions still shaping trust.
              </p>

              <div className="mt-5 flex flex-wrap gap-2">
                <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${status?.tone ?? "bg-slate-800 text-slate-200"}`}>
                  <Radar className="h-3.5 w-3.5" />
                  {status?.label ?? "Collecting evidence"}
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-800/80 px-3 py-1 text-xs font-medium text-slate-200 ring-1 ring-slate-700">
                  <Orbit className="h-3.5 w-3.5" />
                  {benchmarkDashboard?.overview.tracked_models.length ?? 0} tracked models
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-800/80 px-3 py-1 text-xs font-medium text-slate-200 ring-1 ring-slate-700">
                  <Activity className="h-3.5 w-3.5" />
                  {trackedSuiteCount} active suites
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-800/80 px-3 py-1 text-xs font-medium text-slate-200 ring-1 ring-slate-700">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  {pressuredCaseCount} pressured cases
                </span>
              </div>
            </div>

            <div className="relative grid gap-3 rounded-2xl border border-slate-800 bg-slate-950/60 p-4 xl:w-[360px]">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                    Field status
                  </p>
                  <p className="mt-2 text-sm text-slate-200">
                    {status?.detail ?? "Arena is waiting for benchmark evidence before it can judge stability or regression pressure."}
                  </p>
                </div>
                <Sparkles className="h-5 w-5 text-amber-500" />
              </div>

              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl bg-slate-900 px-3 py-2 ring-1 ring-slate-800">
                  <dt className="text-xs uppercase tracking-wide text-slate-400">
                    Last run
                  </dt>
                  <dd className="mt-1 font-semibold text-slate-100">
                    {formatRelativeTime(benchmarkDashboard?.overview.latest_completed_at)}
                  </dd>
                </div>
                <div className="rounded-xl bg-slate-900 px-3 py-2 ring-1 ring-slate-800">
                  <dt className="text-xs uppercase tracking-wide text-slate-400">
                    Best model
                  </dt>
                  <dd className="mt-1 font-semibold text-slate-100">
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
            <div className="flex flex-col gap-3 text-sm text-slate-300 lg:flex-row lg:items-center lg:justify-between">
              <p className="max-w-3xl">
                Arena is where benchmark suites, experiments, regressions, and runtime evidence stay visible enough to guide real prompt, harness, and model decisions instead of anecdotal tuning.
              </p>
              <button
                type="button"
                onClick={() =>
                  setActiveView(activeView === "runtime" ? "overview" : "runtime")
                }
                className="inline-flex items-center gap-2 rounded-xl bg-slate-800 px-4 py-2 text-sm font-medium text-slate-100 transition-colors hover:bg-slate-700"
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
