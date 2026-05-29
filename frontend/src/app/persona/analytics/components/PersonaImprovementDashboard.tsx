'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Gauge,
  Loader2,
  RefreshCw,
  ShieldCheck,
  TimerReset,
} from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useMemo, useState } from 'react'

import type {
  AgentBenchmarkAttemptDetail,
  AgentBenchmarkRunDetail,
} from '@/app/agents/lib/types'
import { ChartCard } from '@/components/charts/ChartCard'
import {
  fetchAgentBenchmarkRunDetail,
  fetchPersonaImprovementDashboard,
  updatePersonaImprovementSchedule,
} from '@/lib/api'
import {
  formatPercent,
  formatRelativeAge,
  formatTokens,
  summarizeIssue,
} from '@/lib/formatters'
import { usePersonaDisplayName } from '../../hooks/usePersonaDisplayName'
import type {
  PersonaImprovementDashboard as PersonaImprovementDashboardData,
  PersonaImprovementRecentRun,
} from '../types'
import { PersonaImprovementTrendSection } from './PersonaImprovementTrendSection'

type DashboardWindow = 7 | 30 | 90

const CADENCE_OPTIONS = [
  { value: 15, label: '15m' },
  { value: 30, label: '30m' },
  { value: 60, label: '1h' },
  { value: 240, label: '4h' },
  { value: 720, label: '12h' },
  { value: 1440, label: '24h' },
]

function formatMetricTokens(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return 'Pending'
  }
  return formatTokens(Math.round(value))
}

function formatMetricDelta(
  current: number | null | undefined,
  average: number | null | undefined,
) {
  if (
    current === null ||
    current === undefined ||
    average === null ||
    average === undefined
  ) {
    return null
  }
  const delta = current - average
  const rounded = Math.abs(delta) < 0.05 ? 0 : Math.round(delta * 10) / 10
  const prefix = rounded > 0 ? '+' : ''
  return `${prefix}${rounded}`
}

function formatRatio(value: number | null | undefined, suffix = '') {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 'Pending'
  }
  const rounded = Math.round(value * 10) / 10
  return `${rounded}${suffix}`
}

function LoadingState() {
  return (
    <div className="page-shell">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />
      <div className="sticky top-0 z-30 border-b border-slate-800 bg-slate-900/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3 lg:px-8">
          <div className="h-6 w-48 animate-pulse rounded bg-slate-800" />
          <div className="h-8 w-36 animate-pulse rounded bg-slate-800" />
        </div>
      </div>
      <main className="relative mx-auto max-w-7xl p-6 lg:p-8">
        <div className="rounded-[20px] border border-slate-800 bg-slate-900/60 p-6 lg:p-8">
          <div className="h-8 w-80 animate-pulse rounded bg-slate-800" />
          <div className="mt-4 h-4 w-96 animate-pulse rounded bg-slate-800" />
        </div>
        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div
              key={index}
              className="rounded-xl border border-slate-800 bg-slate-900 p-5"
            >
              <div className="h-3 w-24 animate-pulse rounded bg-slate-800" />
              <div className="mt-3 h-8 w-20 animate-pulse rounded bg-slate-800" />
            </div>
          ))}
        </div>
      </main>
    </div>
  )
}

function MetricSurfaceCard({
  label,
  icon: Icon,
  colorClass,
  labLabel,
  labValue,
  fieldLabel,
  fieldValue,
  hint,
}: {
  label: string
  icon: React.ElementType
  colorClass: string
  labLabel: string
  labValue: string
  fieldLabel: string
  fieldValue: string
  hint?: string
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400">
            {label}
          </p>
          <dl className="mt-3 space-y-3">
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-slate-500">
                {labLabel}
              </dt>
              <dd className="mt-1 text-xl font-semibold text-slate-100">
                {labValue}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-slate-500">
                {fieldLabel}
              </dt>
              <dd className="mt-1 text-xl font-semibold text-slate-100">
                {fieldValue}
              </dd>
            </div>
          </dl>
          {hint ? <p className="mt-3 text-xs text-slate-500">{hint}</p> : null}
        </div>
        <div className={`rounded-lg p-2.5 ${colorClass}`}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  )
}

function AttemptRow({ attempt }: { attempt: AgentBenchmarkAttemptDetail }) {
  return (
    <div
      className={`flex items-center gap-3 rounded-xl px-3 py-2 text-sm ${
        attempt.passed ? 'bg-emerald-950/20' : 'bg-rose-950/20'
      }`}
    >
      <span
        className={`h-2 w-2 rounded-full ${attempt.passed ? 'bg-emerald-500' : 'bg-rose-500'}`}
      />
      <span className="min-w-0 flex-1 truncate font-medium text-slate-100">
        {attempt.case_name ?? attempt.case_id}
      </span>
      <span className="shrink-0 text-xs text-slate-400">
        {attempt.model_id}
      </span>
      <span className="shrink-0 w-16 text-right text-xs text-slate-400">
        {attempt.total_tokens} tok
      </span>
    </div>
  )
}

function RunDetailPanel({
  expandedRunId,
  runDetail,
  runDetailLoading,
}: {
  expandedRunId: string | null
  runDetail: AgentBenchmarkRunDetail | null
  runDetailLoading: boolean
}) {
  if (!expandedRunId) {
    return null
  }
  if (runDetailLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
      </div>
    )
  }
  if (!runDetail) {
    return null
  }

  const failedAttempts = runDetail.attempts.filter((attempt) => !attempt.passed)
  const passedAttempts = runDetail.attempts.filter((attempt) => attempt.passed)

  return (
    <div className="mt-3 space-y-2">
      {failedAttempts.length > 0 ? (
        <>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-rose-400">
            Failed ({failedAttempts.length})
          </p>
          {failedAttempts.map((attempt) => (
            <div key={attempt.id}>
              <AttemptRow attempt={attempt} />
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
          {passedAttempts.map((attempt) => (
            <AttemptRow key={attempt.id} attempt={attempt} />
          ))}
        </>
      ) : null}
    </div>
  )
}

function RecentRunsSection({
  recentRuns,
  expandedRunId,
  runDetail,
  runDetailLoading,
  onRunClick,
  personaName,
}: {
  recentRuns: PersonaImprovementRecentRun[]
  expandedRunId: string | null
  runDetail: AgentBenchmarkRunDetail | null
  runDetailLoading: boolean
  onRunClick: (runId: string) => void
  personaName: string
}) {
  return (
    <ChartCard title="Recent Runs">
      {recentRuns.length === 0 ? (
        <p className="text-sm text-slate-400">
          No {personaName} improvement runs yet.
        </p>
      ) : (
        <div className="space-y-3">
          {recentRuns.map((run) => {
            const isExpanded = expandedRunId === run.run_id
            return (
              <article
                key={run.run_id}
                aria-expanded={isExpanded}
                onClick={() => onRunClick(run.run_id)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    onRunClick(run.run_id)
                  }
                }}
                className={`cursor-pointer rounded-2xl border px-4 py-4 transition-colors ${
                  isExpanded
                    ? 'border-amber-800 bg-amber-950/20'
                    : 'border-slate-800 bg-slate-950/50 hover:border-slate-700'
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-100">
                      {run.run_kind.replaceAll('_', ' ')}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      {formatRelativeAge(run.completed_at)}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <span className="rounded-full bg-emerald-950/30 px-2 py-1 text-emerald-300 ring-1 ring-emerald-900">
                      reliability {formatPercent(run.reliability)}
                    </span>
                    <span className="rounded-full bg-blue-950/30 px-2 py-1 text-blue-300 ring-1 ring-blue-900">
                      effectiveness {formatPercent(run.effectiveness)}
                    </span>
                    <span className="rounded-full bg-amber-950/30 px-2 py-1 text-amber-300 ring-1 ring-amber-900">
                      {formatMetricTokens(run.tokens_per_passed_attempt)} tok /
                      pass
                    </span>
                    {run.experiment_decision ? (
                      <span
                        className={`rounded-full px-2 py-1 ring-1 ${
                          run.experiment_decision === 'promote'
                            ? 'bg-emerald-950/30 text-emerald-300 ring-emerald-900'
                            : run.experiment_decision === 'rollback'
                              ? 'bg-rose-950/30 text-rose-300 ring-rose-900'
                              : 'bg-amber-950/30 text-amber-300 ring-amber-900'
                        }`}
                      >
                        {run.experiment_decision}
                        {run.decision_source ? ` · ${run.decision_source}` : ''}
                      </span>
                    ) : null}
                  </div>
                </div>

                <dl className="mt-4 grid grid-cols-2 gap-3 text-sm xl:grid-cols-4">
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-slate-400">
                      Cases
                    </dt>
                    <dd className="mt-1 font-medium text-slate-100">
                      {run.case_ids.length}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-slate-400">
                      Passed
                    </dt>
                    <dd className="mt-1 font-medium text-slate-100">
                      {run.passed_attempt_count}/{run.attempt_count}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-slate-400">
                      Prompt
                    </dt>
                    <dd className="mt-1 font-medium text-slate-100">
                      {formatMetricTokens(run.prompt_tokens)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-slate-400">
                      Failures
                    </dt>
                    <dd className="mt-1 font-medium text-slate-100">
                      {run.failure_count ?? 0}
                    </dd>
                  </div>
                </dl>

                <p className="mt-4 text-xs text-slate-400">
                  {run.experiment_decision_reason
                    ? summarizeIssue(run.experiment_decision_reason, 120)
                    : run.top_failure_detail
                      ? summarizeIssue(run.top_failure_detail, 120)
                      : 'No active failure signature in this run.'}
                </p>

                {isExpanded ? (
                  <RunDetailPanel
                    expandedRunId={expandedRunId}
                    runDetail={runDetail}
                    runDetailLoading={runDetailLoading}
                  />
                ) : null}
              </article>
            )
          })}
        </div>
      )}
    </ChartCard>
  )
}

function RiskSection({
  dashboard,
  personaName,
}: {
  dashboard: PersonaImprovementDashboardData
  personaName: string
}) {
  const hasScheduleRisks = dashboard.schedule_risks.length > 0
  const hasFieldRisks = dashboard.field_risks.length > 0
  const hasLabRisks = dashboard.open_regressions.length > 0
  const hasFieldReviewGate = dashboard.field_review_gate.needs_review

  return (
    <ChartCard title="Current Risks">
      {!hasScheduleRisks &&
      !hasFieldRisks &&
      !hasLabRisks &&
      !hasFieldReviewGate ? (
        <p className="text-sm text-slate-400">
          No open {personaName} schedule, field, or lab risks.
        </p>
      ) : (
        <div className="space-y-3">
          {hasFieldReviewGate ? (
            <div className="rounded-2xl border border-amber-900/40 bg-amber-950/15 px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-slate-100">
                  Field review
                </p>
                <span className="text-xs font-medium text-amber-300">
                  {dashboard.field_review_gate.reason_codes.join(', ') ||
                    'review'}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-300">
                {dashboard.field_review_gate.summary}
              </p>
              <p className="mt-2 text-xs text-slate-500">
                {dashboard.field_window_lab_runs} lab runs vs{' '}
                {dashboard.field_overview.total_heartbeats} real heartbeats in
                the last {dashboard.field_window_days}d
              </p>
            </div>
          ) : null}
          {dashboard.schedule_risks.map((item) => (
            <div
              key={`${item.kind}:${item.detail ?? item.summary}`}
              className={`rounded-2xl border px-4 py-3 ${
                item.critical
                  ? 'border-amber-900/40 bg-amber-950/15'
                  : 'border-slate-800 bg-slate-950/50'
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-slate-100">
                  Scheduler
                </p>
                <span
                  className={`text-xs font-medium ${
                    item.critical ? 'text-amber-300' : 'text-slate-400'
                  }`}
                >
                  {item.kind}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-300">{item.summary}</p>
              <p className="mt-2 text-xs text-slate-500">
                {item.detail ? summarizeIssue(item.detail, 140) : 'No detail'}
              </p>
            </div>
          ))}
          {dashboard.field_risks.map((item) => (
            <div
              key={item.session_id}
              className={`rounded-2xl border px-4 py-3 ${
                item.critical
                  ? 'border-amber-900/40 bg-amber-950/15'
                  : 'border-slate-800 bg-slate-950/50'
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-slate-100">
                  Real heartbeat
                </p>
                <span
                  className={`text-xs font-medium ${
                    item.critical ? 'text-amber-300' : 'text-slate-400'
                  }`}
                >
                  {formatPercent(item.reliability)}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-300">
                {item.issue_summary}
              </p>
              <p className="mt-2 text-xs text-slate-500">
                {item.summary_oneliner
                  ? summarizeIssue(item.summary_oneliner, 120)
                  : 'No summary'}
              </p>
              <p className="mt-2 text-xs text-slate-500">
                seen {formatRelativeAge(item.completed_at)}
              </p>
            </div>
          ))}
          {dashboard.open_regressions.map((item) => (
            <div
              key={`${item.case_id}:${item.failure_detail}`}
              className="rounded-2xl border border-rose-900/40 bg-rose-950/15 px-4 py-3"
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-slate-100">
                  {item.case_id}
                </p>
                <span className="text-xs font-medium text-rose-300">
                  {item.occurrence_count}x
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-300">
                {summarizeIssue(item.failure_detail, 160)}
              </p>
              <p className="mt-2 text-xs text-slate-500">
                last seen {formatRelativeAge(item.last_seen_at)}
              </p>
            </div>
          ))}
        </div>
      )}
    </ChartCard>
  )
}

function FieldRealitySection({
  dashboard,
  labRunsPerHeartbeat,
}: {
  dashboard: PersonaImprovementDashboardData
  labRunsPerHeartbeat: number | null
}) {
  const items = [
    {
      label: 'Healthy rate',
      value: formatPercent(dashboard.field_overview.healthy_rate),
      detail: `${dashboard.field_overview.healthy_heartbeats}/${dashboard.field_overview.total_heartbeats} clean heartbeats`,
    },
    {
      label: 'Action rate',
      value: formatPercent(dashboard.field_overview.action_rate),
      detail: `${dashboard.field_overview.action_heartbeats}/${dashboard.field_overview.total_heartbeats} movement heartbeats`,
    },
    {
      label: 'Partial rate',
      value: formatPercent(dashboard.field_overview.partial_rate),
      detail: `${dashboard.field_overview.partial_heartbeats}/${dashboard.field_overview.total_heartbeats} partial heartbeats`,
    },
    {
      label: 'Repeated issue',
      value: dashboard.field_overview.top_issue_label
        ? `${dashboard.field_overview.top_issue_label} x${dashboard.field_overview.top_issue_count}`
        : 'None',
      detail: dashboard.field_overview.top_issue_label
        ? 'Most common real-heartbeat miss in the selected window'
        : 'No repeated field issue in the selected window',
    },
    {
      label: 'Lab pressure',
      value: formatRatio(labRunsPerHeartbeat, ' runs / HB'),
      detail: `${dashboard.field_window_lab_runs} lab runs vs ${dashboard.field_overview.total_heartbeats} real heartbeats in the last ${dashboard.field_window_days}d`,
    },
  ]

  return (
    <ChartCard title="Field Reality">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-5">
        {items.map((item) => (
          <div
            key={item.label}
            className="rounded-2xl border border-slate-800 bg-slate-950/50 px-4 py-4"
          >
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
              {item.label}
            </p>
            <p className="mt-2 text-sm font-semibold text-slate-100">
              {item.value}
            </p>
            <p className="mt-2 text-xs leading-5 text-slate-500">
              {item.detail}
            </p>
          </div>
        ))}
      </div>
    </ChartCard>
  )
}

export function PersonaImprovementDashboard() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const { personaName, personaPossessive } = usePersonaDisplayName()
  const [windowDays, setWindowDays] = useState<DashboardWindow>(30)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  const [runDetail, setRunDetail] = useState<AgentBenchmarkRunDetail | null>(
    null,
  )
  const [runDetailLoading, setRunDetailLoading] = useState(false)
  const [enabled, setEnabled] = useState(false)
  const [cadenceMinutes, setCadenceMinutes] = useState(1440)

  const {
    data: dashboard,
    isLoading,
    error,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ['persona-improvement', windowDays],
    queryFn: () => fetchPersonaImprovementDashboard(windowDays, 8),
  })

  useEffect(() => {
    if (!dashboard) {
      return
    }
    setEnabled(dashboard.schedule.enabled)
    setCadenceMinutes(dashboard.schedule.cadence_minutes)
  }, [dashboard])

  const scheduleMutation = useMutation({
    mutationFn: updatePersonaImprovementSchedule,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['persona-improvement'] })
    },
  })

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
        const detail = await fetchAgentBenchmarkRunDetail('persona', runId)
        setRunDetail(detail)
      } catch {
        setRunDetail(null)
      } finally {
        setRunDetailLoading(false)
      }
    },
    [expandedRunId],
  )

  const hasScheduleChanges = useMemo(() => {
    if (!dashboard) {
      return false
    }
    return (
      enabled !== dashboard.schedule.enabled ||
      cadenceMinutes !== dashboard.schedule.cadence_minutes
    )
  }, [cadenceMinutes, dashboard, enabled])

  const cadenceLabel = useMemo(() => {
    const option = CADENCE_OPTIONS.find(
      (candidate) => candidate.value === cadenceMinutes,
    )
    if (option) {
      return option.label
    }
    if (cadenceMinutes < 60) {
      return `${cadenceMinutes}m`
    }
    return `${Math.round(cadenceMinutes / 60)}h`
  }, [cadenceMinutes])

  const statusTone = useMemo(() => {
    if (!dashboard) {
      return 'bg-slate-800 text-slate-300 ring-1 ring-slate-700'
    }
    if (
      dashboard.schedule_risks.some((item) => item.critical) ||
      (dashboard.overview.open_regressions ?? 0) > 0 ||
      dashboard.field_risks.some((item) => item.critical)
    ) {
      return 'bg-rose-950/30 text-rose-300 ring-1 ring-rose-800'
    }
    if (!dashboard.schedule.enabled) {
      return 'bg-amber-950/30 text-amber-300 ring-1 ring-amber-800'
    }
    return 'bg-emerald-950/30 text-emerald-300 ring-1 ring-emerald-800'
  }, [dashboard])

  if (isLoading) {
    return <LoadingState />
  }

  if (error || !dashboard) {
    const message =
      error instanceof Error
        ? error.message
        : `Failed to load ${personaName} improvement dashboard`
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />
        <div className="relative max-w-md rounded-2xl border border-rose-900 bg-slate-900/90 p-8 text-center">
          <AlertTriangle className="mx-auto mb-3 h-10 w-10 text-rose-500" />
          <p className="text-sm font-semibold text-slate-100">
            {personaName} improvement unavailable
          </p>
          <p className="mt-2 text-sm text-slate-400">{message}</p>
        </div>
      </div>
    )
  }

  const latestLabRun = dashboard.latest_lab_run
  const latestFieldHeartbeat = dashboard.recent_heartbeats[0]
  const reliabilityDelta = formatMetricDelta(
    latestLabRun?.reliability,
    dashboard.overview.reliability,
  )
  const fieldReliabilityDelta = formatMetricDelta(
    latestFieldHeartbeat?.reliability,
    dashboard.field_overview.reliability,
  )
  const effectivenessDelta = formatMetricDelta(
    latestLabRun?.effectiveness,
    dashboard.overview.effectiveness,
  )
  const fieldEffectivenessDelta = formatMetricDelta(
    latestFieldHeartbeat?.effectiveness,
    dashboard.field_overview.effectiveness,
  )
  const tokenDelta = formatMetricDelta(
    latestLabRun?.tokens_per_passed_attempt,
    dashboard.overview.tokens_per_passed_attempt,
  )
  const fieldTokenDelta = formatMetricDelta(
    latestFieldHeartbeat?.total_tokens,
    dashboard.field_overview.tokens_per_healthy_heartbeat,
  )
  const promptDelta = formatMetricDelta(
    latestLabRun?.prompt_tokens,
    dashboard.overview.prompt_tokens,
  )
  const fieldTruthDelta = formatMetricDelta(
    latestFieldHeartbeat?.truth_quality,
    dashboard.field_overview.truth_quality,
  )
  const labRunsPerHeartbeat =
    dashboard.field_overview.total_heartbeats > 0
      ? dashboard.field_window_lab_runs /
        dashboard.field_overview.total_heartbeats
      : null

  const saveErrorMessage =
    scheduleMutation.error instanceof Error
      ? scheduleMutation.error.message
      : null

  return (
    <div className="page-shell">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-900/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-7xl flex-col gap-3 px-6 py-3 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => router.push('/persona')}
              className="rounded-lg p-1.5 transition-colors hover:bg-slate-800"
              aria-label="Back"
            >
              <ArrowLeft className="h-5 w-5 text-slate-400" />
            </button>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold tracking-tight text-slate-100">
                  {personaName} Improvement
                </h1>
                <span
                  className={`rounded px-2 py-0.5 text-xs font-semibold ${statusTone}`}
                >
                  {dashboard.schedule.enabled ? 'Scheduled' : 'Paused'}
                </span>
              </div>
              <p className="text-sm text-slate-400">
                Focused on protected lab wins and recent real-heartbeat field
                performance.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center rounded-lg border border-slate-700 bg-slate-800 p-0.5">
              {([7, 30, 90] as DashboardWindow[]).map((days) => (
                <button
                  key={days}
                  type="button"
                  onClick={() => setWindowDays(days)}
                  className={`rounded-md px-3 py-1 text-xs font-medium transition-all duration-150 ${
                    windowDays === days
                      ? 'bg-amber-500 text-slate-950 shadow-sm'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {days}d
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => void refetch()}
              disabled={isRefetching}
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-700 disabled:opacity-50"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${isRefetching ? 'animate-spin' : ''}`}
              />
              Refresh
            </button>
          </div>
        </div>
      </header>

      <main className="relative mx-auto max-w-7xl p-6 lg:p-8">
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <section className="rounded-[24px] border border-slate-800 bg-slate-900/70 p-6 lg:p-8">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-amber-300">
              Improvement Loop
            </p>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-50">
              One place to manage {personaPossessive} honing loop.
            </h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
              This view keeps the fast protected evaluator and the outer-loop
              real heartbeat signal in one place. It answers whether{' '}
              {personaName} is reliable, whether {personaName} is moving the
              right work, and what token/context cost it takes to get there in
              the lab and in the field.
            </p>
            <div className="mt-5 flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-slate-800 px-3 py-1 text-slate-300 ring-1 ring-slate-700">
                last run{' '}
                {formatRelativeAge(dashboard.overview.latest_completed_at)}
              </span>
              {latestLabRun ? (
                <span className="rounded-full bg-emerald-950/20 px-3 py-1 text-emerald-300 ring-1 ring-emerald-900/60">
                  current lab {formatPercent(latestLabRun.reliability)}{' '}
                  reliability
                </span>
              ) : null}
              {latestFieldHeartbeat ? (
                <span className="rounded-full bg-blue-950/20 px-3 py-1 text-blue-300 ring-1 ring-blue-900/60">
                  current field{' '}
                  {formatPercent(latestFieldHeartbeat.reliability)} reliability
                </span>
              ) : null}
              <span className="rounded-full bg-slate-800 px-3 py-1 text-slate-300 ring-1 ring-slate-700">
                {dashboard.overview.total_runs} runs in window
              </span>
              <span className="rounded-full bg-slate-800 px-3 py-1 text-slate-300 ring-1 ring-slate-700">
                suite {dashboard.suite_id}
              </span>
            </div>
          </section>

          <ChartCard title="Honing Controls">
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold text-slate-100">
                    Scheduled self-improvement
                  </p>
                  <p className="text-xs text-slate-400">
                    Turn the recurring {personaName} improvement loop on or off.
                  </p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={enabled}
                  onClick={() => setEnabled((current) => !current)}
                  className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors ${
                    enabled ? 'bg-emerald-500' : 'bg-slate-700'
                  }`}
                >
                  <span
                    className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform ${
                      enabled ? 'translate-x-6' : 'translate-x-1'
                    }`}
                  />
                </button>
              </div>

              <label className="block text-sm">
                <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
                  Frequency
                </span>
                <select
                  value={cadenceMinutes}
                  onChange={(event) =>
                    setCadenceMinutes(Number(event.target.value))
                  }
                  className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none transition-colors focus:border-amber-500"
                >
                  {CADENCE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      Every {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl bg-slate-950/70 px-3 py-3">
                  <dt className="text-xs uppercase tracking-wide text-slate-400">
                    Next run
                  </dt>
                  <dd className="mt-1 font-medium text-slate-100">
                    {dashboard.schedule.enabled
                      ? formatRelativeAge(dashboard.schedule.next_run_at)
                      : 'Paused'}
                  </dd>
                </div>
                <div className="rounded-xl bg-slate-950/70 px-3 py-3">
                  <dt className="text-xs uppercase tracking-wide text-slate-400">
                    Cadence
                  </dt>
                  <dd className="mt-1 font-medium text-slate-100">
                    {cadenceLabel}
                  </dd>
                </div>
              </dl>

              <p className="text-xs text-slate-500">
                Last run {formatRelativeAge(dashboard.schedule.last_run_at)} ·
                total runs {dashboard.schedule.run_count} · overlap skips
                instead of stacking
              </p>

              {saveErrorMessage ? (
                <p className="text-sm text-rose-400">{saveErrorMessage}</p>
              ) : null}

              <button
                type="button"
                onClick={() =>
                  scheduleMutation.mutate({
                    enabled,
                    cadence_minutes: cadenceMinutes,
                  })
                }
                disabled={!hasScheduleChanges || scheduleMutation.isPending}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-amber-500 px-4 py-2 text-sm font-semibold text-slate-950 transition-colors hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {scheduleMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : null}
                Save controls
              </button>
            </div>
          </ChartCard>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricSurfaceCard
            label="Reliability"
            icon={ShieldCheck}
            colorClass="bg-emerald-950/30 text-emerald-400"
            labLabel="Current lab"
            labValue={formatPercent(
              latestLabRun?.reliability ?? dashboard.overview.reliability,
            )}
            fieldLabel="Current field"
            fieldValue={formatPercent(
              latestFieldHeartbeat?.reliability ??
                dashboard.field_overview.reliability,
            )}
            hint={`lab avg ${formatPercent(dashboard.overview.reliability)}${reliabilityDelta !== null ? ` · lab Δ ${reliabilityDelta}` : ''} · field avg ${formatPercent(dashboard.field_overview.reliability)}${fieldReliabilityDelta !== null ? ` · field Δ ${fieldReliabilityDelta}` : ''}`}
          />
          <MetricSurfaceCard
            label="Effectiveness"
            icon={Activity}
            colorClass="bg-blue-950/30 text-blue-400"
            labLabel="Current lab"
            labValue={formatPercent(
              latestLabRun?.effectiveness ?? dashboard.overview.effectiveness,
            )}
            fieldLabel="Current field"
            fieldValue={formatPercent(
              latestFieldHeartbeat?.effectiveness ??
                dashboard.field_overview.effectiveness,
            )}
            hint={`lab avg ${formatPercent(dashboard.overview.effectiveness)}${effectivenessDelta !== null ? ` · lab Δ ${effectivenessDelta}` : ''} · field avg ${formatPercent(dashboard.field_overview.effectiveness)}${fieldEffectivenessDelta !== null ? ` · field Δ ${fieldEffectivenessDelta}` : ''}`}
          />
          <MetricSurfaceCard
            label="Token Efficiency"
            icon={Gauge}
            colorClass="bg-amber-950/30 text-amber-400"
            labLabel="Current lab tok / pass"
            labValue={formatMetricTokens(
              latestLabRun?.tokens_per_passed_attempt ??
                dashboard.overview.tokens_per_passed_attempt,
            )}
            fieldLabel="Current HB tokens"
            fieldValue={formatMetricTokens(
              latestFieldHeartbeat?.total_tokens ??
                dashboard.field_overview.tokens_per_healthy_heartbeat,
            )}
            hint={`lab avg ${formatMetricTokens(dashboard.overview.tokens_per_passed_attempt)}${tokenDelta !== null ? ` · lab Δ ${tokenDelta}` : ''} · field avg ${formatMetricTokens(dashboard.field_overview.tokens_per_healthy_heartbeat)}${fieldTokenDelta !== null ? ` · field Δ ${fieldTokenDelta}` : ''}`}
          />
          <MetricSurfaceCard
            label="Context And Truth"
            icon={TimerReset}
            colorClass="bg-rose-950/30 text-rose-400"
            labLabel="Current prompt"
            labValue={formatMetricTokens(
              latestLabRun?.prompt_tokens ?? dashboard.overview.prompt_tokens,
            )}
            fieldLabel="Current truth"
            fieldValue={formatPercent(
              latestFieldHeartbeat?.truth_quality ??
                dashboard.field_overview.truth_quality,
            )}
            hint={`lab avg ${formatMetricTokens(dashboard.overview.prompt_tokens)}${promptDelta !== null ? ` · lab Δ ${promptDelta}` : ''} · field avg ${formatPercent(dashboard.field_overview.truth_quality)}${fieldTruthDelta !== null ? ` · field Δ ${fieldTruthDelta}` : ''} · ${dashboard.overview.open_regressions} open lab regressions`}
          />
        </div>

        <div className="mt-6">
          <FieldRealitySection
            dashboard={dashboard}
            labRunsPerHeartbeat={labRunsPerHeartbeat}
          />
        </div>

        <div className="mt-6">
          <PersonaImprovementTrendSection
            labTrend={dashboard.trend}
            fieldTrend={dashboard.field_trend}
            personaName={personaName}
          />
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <RecentRunsSection
            recentRuns={dashboard.recent_runs}
            expandedRunId={expandedRunId}
            runDetail={runDetail}
            runDetailLoading={runDetailLoading}
            onRunClick={handleRunClick}
            personaName={personaName}
          />
          <RiskSection dashboard={dashboard} personaName={personaName} />
        </div>
      </main>
    </div>
  )
}
