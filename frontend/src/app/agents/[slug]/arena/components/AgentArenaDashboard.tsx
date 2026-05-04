'use client'

import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  FlaskConical,
  Orbit,
  Radar,
  Sparkles,
} from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { BenchmarkExperimentSection } from '@/app/agents/[slug]/analytics/components/BenchmarkExperimentSection'
import { ChartCard } from '@/app/agents/[slug]/analytics/components/ChartCard'
import type { AgentBenchmarkRunDetail } from '@/app/agents/[slug]/analytics/types'
import { metricsToAnalytics } from '@/app/agents/[slug]/analytics/utils'
import { deriveArenaStatus, formatRelativeTime } from '@/app/arena/utils'
import {
  fetchAgent,
  fetchAgentBenchmarkDashboard,
  fetchAgentBenchmarkRunDetail,
  fetchAgentMetrics,
} from '@/lib/api'

import { ArenaHeader, type ArenaView, type ArenaWindow } from './ArenaHeader'
import {
  sortCases,
  sortModels,
  sortRegressions,
  sortRuns,
  sortSuites,
} from './arenaSort'
import { OverviewPanels } from './OverviewPanels'
import { RecentRunsCard } from './RecentRunsCard'
import { RegressionWatchlist } from './RegressionWatchlist'
import { RuntimePanels } from './RuntimePanels'
import { SuitePanels } from './SuitePanels'

interface AgentArenaDashboardProps {
  slug: string
  backHref?: string
  initialView?: ArenaView
}

function SkeletonBlock({ className }: { className: string }) {
  return <div className={`rounded bg-slate-800 animate-shimmer ${className}`} />
}

function LoadingSkeleton() {
  return (
    <div className="page-shell">
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
            <div
              key={i}
              className="rounded-xl border border-slate-800 bg-slate-900/60 p-5"
            >
              <SkeletonBlock className="h-3 w-24" />
              <SkeletonBlock className="mt-3 h-7 w-16" />
            </div>
          ))}
        </div>
      </main>
    </div>
  )
}

export function AgentArenaDashboard({
  slug,
  backHref,
  initialView = 'overview',
}: AgentArenaDashboardProps) {
  const [windowDays, setWindowDays] = useState<ArenaWindow>(30)
  const [activeView, setActiveView] = useState<ArenaView>(initialView)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  const [runDetail, setRunDetail] = useState<AgentBenchmarkRunDetail | null>(
    null,
  )
  const [runDetailLoading, setRunDetailLoading] = useState(false)

  const handleRunClick = useCallback(
    async (runId: string) => {
      if (expandedRunId === runId) {
        setExpandedRunId(null)
        setRunDetail(null)
        return
      }
      setExpandedRunId(runId)
      setRunDetail(null)
      setRunDetailLoading(true)
      try {
        const detail = await fetchAgentBenchmarkRunDetail(slug, runId)
        setRunDetail(detail)
      } catch {
        setRunDetail(null)
      } finally {
        setRunDetailLoading(false)
      }
    },
    [expandedRunId, slug],
  )

  const {
    data: agent,
    isLoading: agentLoading,
    error: agentError,
    refetch: refetchAgent,
    isRefetching: agentRefetching,
  } = useQuery({
    queryKey: ['agent', slug],
    queryFn: () => fetchAgent(slug),
    enabled: !!slug,
  })
  const {
    data: metrics,
    isLoading: metricsLoading,
    error: metricsError,
    refetch: refetchMetrics,
    isRefetching: metricsRefetching,
  } = useQuery({
    queryKey: ['agent-metrics', slug],
    queryFn: () => fetchAgentMetrics(slug),
    enabled: !!slug,
  })
  const {
    data: benchmarkDashboard,
    isLoading: benchmarkLoading,
    error: benchmarkError,
    refetch: refetchBenchmarks,
    isRefetching: benchmarksRefetching,
  } = useQuery({
    queryKey: ['agent-benchmarks', slug, windowDays],
    queryFn: () => fetchAgentBenchmarkDashboard(slug, windowDays, 24),
    enabled: !!slug,
  })

  const isLoading = agentLoading || metricsLoading || benchmarkLoading
  const error = agentError
  const isRefreshing =
    agentRefetching || metricsRefetching || benchmarksRefetching
  const analytics = agent && metrics ? metricsToAnalytics(metrics, agent) : null
  const benchmarkErrorMessage =
    benchmarkError instanceof Error ? benchmarkError.message : null
  const runtimeErrorMessage =
    metricsError instanceof Error ? metricsError.message : null

  const status = useMemo(
    () => (benchmarkDashboard ? deriveArenaStatus(benchmarkDashboard) : null),
    [benchmarkDashboard],
  )
  const sortedModels = useMemo(
    () => sortModels(benchmarkDashboard?.model_performance ?? []).slice(0, 5),
    [benchmarkDashboard],
  )
  const sortedSuites = useMemo(
    () => sortSuites(benchmarkDashboard?.suites ?? []).slice(0, 8),
    [benchmarkDashboard],
  )
  const sortedCases = useMemo(
    () => sortCases(benchmarkDashboard?.cases ?? []).slice(0, 10),
    [benchmarkDashboard],
  )
  const recentRuns = useMemo(
    () => sortRuns(benchmarkDashboard?.recent_runs ?? []).slice(0, 6),
    [benchmarkDashboard],
  )
  const regressions = useMemo(
    () =>
      sortRegressions(benchmarkDashboard?.open_regressions ?? []).slice(0, 6),
    [benchmarkDashboard],
  )

  const trackedSuiteCount = benchmarkDashboard?.suites.length ?? 0
  const pressuredCaseCount = sortedCases.filter(
    (s) => s.open_regressions > 0,
  ).length
  const primaryModel = agent?.primary_model_id ?? null
  const bestModel = sortedModels[0] ?? null
  const hasHistory = (benchmarkDashboard?.overview.total_runs ?? 0) > 0
  const hasRuntimeActivity = analytics
    ? analytics.totalRequests > 0 ||
      analytics.totalTokens > 0 ||
      analytics.totalCostUsd > 0
    : false

  const runtimePanelProps = {
    analytics,
    primaryModel,
    hasRuntimeActivity,
    runtimeErrorMessage,
  }
  const runCardProps = {
    recentRuns,
    expandedRunId,
    runDetail,
    runDetailLoading,
    onRunClick: handleRunClick,
  }

  function handleRefresh() {
    void Promise.all([refetchAgent(), refetchMetrics(), refetchBenchmarks()])
  }

  function renderActivePanels() {
    if (activeView === 'runtime') {
      return <RuntimePanels {...runtimePanelProps} />
    }

    if (activeView === 'suites') {
      return (
        <SuitePanels sortedSuites={sortedSuites} sortedCases={sortedCases} />
      )
    }

    if (activeView === 'experiments') {
      if (!benchmarkDashboard) {
        return (
          <div className="mt-6">
            <ChartCard title="Experiments">
              <p className="text-sm text-slate-400">
                {benchmarkErrorMessage ??
                  'No benchmark experiments are available.'}
              </p>
            </ChartCard>
          </div>
        )
      }
      return (
        <>
          <div className="mt-6">
            {benchmarkDashboard.experiments.length > 0 ? (
              <BenchmarkExperimentSection
                experiments={benchmarkDashboard.experiments}
              />
            ) : (
              <ChartCard title="Experiments">
                <p className="text-sm text-slate-400">
                  No persisted experiments yet. Arena will surface cohort
                  comparisons here once runs are being promoted or held.
                </p>
              </ChartCard>
            )}
          </div>
          <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[1.1fr_0.9fr]">
            <RecentRunsCard
              {...runCardProps}
              title="Recent experimental runs"
            />
            <RegressionWatchlist regressions={regressions} />
          </div>
        </>
      )
    }

    return (
      <OverviewPanels
        benchmarkDashboard={benchmarkDashboard}
        sortedModels={sortedModels}
        sortedSuites={sortedSuites}
        sortedCases={sortedCases}
        recentRuns={recentRuns}
        regressions={regressions}
        primaryModel={primaryModel}
        slug={slug}
        hasHistory={hasHistory}
        benchmarkErrorMessage={benchmarkErrorMessage}
        analytics={analytics}
        hasRuntimeActivity={hasRuntimeActivity}
        runtimeErrorMessage={runtimeErrorMessage}
        expandedRunId={expandedRunId}
        runDetail={runDetail}
        runDetailLoading={runDetailLoading}
        onRunClick={handleRunClick}
      />
    )
  }

  if (isLoading) return <LoadingSkeleton />

  if (error) {
    const errorMessage =
      error instanceof Error ? error.message : 'Failed to load Arena'
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />
        <div className="relative max-w-md rounded-2xl border border-rose-900 bg-slate-900/90 p-8 text-center">
          <AlertCircle className="mx-auto mb-3 h-10 w-10 text-rose-500" />
          <p className="text-sm font-semibold text-slate-100">
            Arena unavailable
          </p>
          <p className="mt-2 text-sm text-slate-400">{errorMessage}</p>
        </div>
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />
        <div className="relative text-center">
          <AlertCircle className="mx-auto mb-3 h-10 w-10 text-rose-500" />
          <p className="text-sm text-slate-400">Agent not found</p>
        </div>
      </div>
    )
  }

  return (
    <div className="page-shell">
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
                Arena turns benchmark history into a readable field report:
                stability, runtime health, controlled experiments, and the
                regressions still shaping trust.
              </p>

              <div className="mt-5 flex flex-wrap gap-2">
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${status?.tone ?? 'bg-slate-800 text-slate-200'}`}
                >
                  <Radar className="h-3.5 w-3.5" />
                  {status?.label ?? 'Collecting evidence'}
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-800/80 px-3 py-1 text-xs font-medium text-slate-200 ring-1 ring-slate-700">
                  <Orbit className="h-3.5 w-3.5" />
                  {benchmarkDashboard?.overview.tracked_models.length ?? 0}{' '}
                  tracked models
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
                    {status?.detail ??
                      'Arena is waiting for benchmark evidence before it can judge stability or regression pressure.'}
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
                    {formatRelativeTime(
                      benchmarkDashboard?.overview.latest_completed_at,
                    )}
                  </dd>
                </div>
                <div className="rounded-xl bg-slate-900 px-3 py-2 ring-1 ring-slate-800">
                  <dt className="text-xs uppercase tracking-wide text-slate-400">
                    Best model
                  </dt>
                  <dd className="mt-1 font-semibold text-slate-100">
                    {bestModel?.model_id ?? primaryModel ?? 'Pending'}
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
                Arena is where benchmark suites, experiments, regressions, and
                runtime evidence stay visible enough to guide real prompt,
                harness, and model decisions instead of anecdotal tuning.
              </p>
              <button
                type="button"
                onClick={() =>
                  setActiveView(
                    activeView === 'runtime' ? 'overview' : 'runtime',
                  )
                }
                className="inline-flex items-center gap-2 rounded-xl bg-slate-800 px-4 py-2 text-sm font-medium text-slate-100 transition-colors hover:bg-slate-700"
              >
                {activeView === 'runtime'
                  ? 'Return to overview'
                  : 'View runtime lens'}
              </button>
            </div>
          </ChartCard>
        </div>
      </main>
    </div>
  )
}
