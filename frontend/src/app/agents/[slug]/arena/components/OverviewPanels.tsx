import { Activity, AlertTriangle, FlaskConical, Trophy } from 'lucide-react'
import { ArenaPreviewCard } from '@/app/agents/[slug]/analytics/components/ArenaPreviewCard'
import { BenchmarkTrendSection } from '@/app/agents/[slug]/analytics/components/BenchmarkTrendSection'
import { ChartCard } from '@/app/agents/[slug]/analytics/components/ChartCard'
import { KPICard } from '@/app/agents/[slug]/analytics/components/KPICard'
import type {
  AgentBenchmarkCaseSummary,
  AgentBenchmarkDashboard,
  AgentBenchmarkModelSummary,
  AgentBenchmarkRunDetail,
  AgentBenchmarkRunSummary,
  AgentBenchmarkSuiteSummary,
  AgentRegressionClusterSummary,
  AnalyticsData,
} from '@/app/agents/[slug]/analytics/types'
import {
  formatPercent,
  formatRelativeTime,
  formatScore,
} from '@/app/arena/utils'
import { formatLatency, formatNumber } from '@/lib/formatters'

import { RecentRunsCard } from './RecentRunsCard'
import { RegressionWatchlist } from './RegressionWatchlist'
import { RuntimePanels } from './RuntimePanels'
import { SuitePanels } from './SuitePanels'

interface OverviewPanelsProps {
  benchmarkDashboard: AgentBenchmarkDashboard | undefined
  sortedModels: AgentBenchmarkModelSummary[]
  sortedSuites: AgentBenchmarkSuiteSummary[]
  sortedCases: AgentBenchmarkCaseSummary[]
  recentRuns: AgentBenchmarkRunSummary[]
  regressions: AgentRegressionClusterSummary[]
  primaryModel: string | null
  slug: string
  hasHistory: boolean
  benchmarkErrorMessage: string | null
  analytics: AnalyticsData | null
  hasRuntimeActivity: boolean
  runtimeErrorMessage: string | null
  expandedRunId: string | null
  runDetail: AgentBenchmarkRunDetail | null
  runDetailLoading: boolean
  onRunClick: (runId: string) => void
}

export function OverviewPanels({
  benchmarkDashboard,
  sortedModels,
  sortedSuites,
  sortedCases,
  recentRuns,
  regressions,
  primaryModel,
  slug,
  hasHistory,
  benchmarkErrorMessage,
  analytics,
  hasRuntimeActivity,
  runtimeErrorMessage,
  expandedRunId,
  runDetail,
  runDetailLoading,
  onRunClick,
}: OverviewPanelsProps) {
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
                {benchmarkErrorMessage ??
                  'No benchmark history is available for this agent yet.'}
              </p>
            </div>
          </ChartCard>
        </div>
        <RuntimePanels
          analytics={analytics}
          primaryModel={primaryModel}
          hasRuntimeActivity={hasRuntimeActivity}
          runtimeErrorMessage={runtimeErrorMessage}
        />
      </>
    )
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
        <RuntimePanels
          analytics={analytics}
          primaryModel={primaryModel}
          hasRuntimeActivity={hasRuntimeActivity}
          runtimeErrorMessage={runtimeErrorMessage}
        />
      </>
    )
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
                const isPrimary = model.model_id === primaryModel
                return (
                  <article
                    key={model.model_id}
                    className={`flex items-center justify-between gap-4 rounded-2xl border px-4 py-3 ${isPrimary ? 'border-amber-900 bg-amber-950/20' : 'border-slate-800 bg-slate-950/50'}`}
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
                        {model.attempts} attempts · last seen{' '}
                        {formatRelativeTime(model.latest_completed_at)}
                      </p>
                      <p className="text-xs text-slate-500">
                        {model.avg_tool_calls ?? '—'} avg tools ·{' '}
                        {model.avg_total_tokens ?? '—'} avg tokens
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
                )
              })}
            </div>
          )}
        </ChartCard>

        <RegressionWatchlist regressions={regressions} />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <ChartCard title="Runtime pulse">
          {runtimeErrorMessage || !analytics ? (
            <p className="text-sm text-slate-400">
              {runtimeErrorMessage ?? 'Runtime metrics are unavailable.'}
            </p>
          ) : (
            <div className="space-y-4">
              {[
                {
                  label: 'Requests',
                  value: formatNumber(analytics.totalRequests),
                },
                { label: 'Success rate', value: `${analytics.successRate}%` },
                {
                  label: 'Average latency',
                  value: formatLatency(analytics.avgLatencyMs),
                },
                { label: 'Primary model', value: primaryModel ?? 'Unassigned' },
              ].map(({ label, value }) => (
                <div
                  key={label}
                  className="flex items-center justify-between text-sm"
                >
                  <span className="text-slate-400">{label}</span>
                  <span className="font-semibold text-slate-100">{value}</span>
                </div>
              ))}
            </div>
          )}
        </ChartCard>

        <RecentRunsCard
          recentRuns={recentRuns}
          expandedRunId={expandedRunId}
          runDetail={runDetail}
          runDetailLoading={runDetailLoading}
          onRunClick={onRunClick}
        />
      </div>

      <SuitePanels sortedSuites={sortedSuites} sortedCases={sortedCases} />
    </>
  )
}
