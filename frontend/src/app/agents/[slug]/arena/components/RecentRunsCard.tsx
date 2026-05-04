import { Loader2 } from 'lucide-react'

import { ChartCard } from '@/app/agents/[slug]/analytics/components/ChartCard'
import type {
  AgentBenchmarkAttemptDetail,
  AgentBenchmarkRunDetail,
  AgentBenchmarkRunSummary,
} from '@/app/agents/[slug]/analytics/types'
import { formatArenaLabel, formatPercent, formatScore } from '@/app/arena/utils'

interface RecentRunsCardProps {
  recentRuns: AgentBenchmarkRunSummary[]
  expandedRunId: string | null
  runDetail: AgentBenchmarkRunDetail | null
  runDetailLoading: boolean
  onRunClick: (runId: string) => void
  title?: string
}

function AttemptRow({ attempt }: { attempt: AgentBenchmarkAttemptDetail }) {
  return (
    <div
      key={attempt.id}
      className={`flex items-center gap-3 rounded-xl px-3 py-2 text-sm ${attempt.passed ? 'bg-emerald-950/20' : 'bg-rose-950/20'}`}
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
      <span className="shrink-0 w-12 text-right font-semibold text-slate-100">
        {attempt.composite_score.toFixed(0)}
      </span>
      <span className="shrink-0 w-16 text-right text-xs text-slate-400">
        {attempt.latency_ms}ms
      </span>
    </div>
  )
}

function RunDrillDown({
  expandedRunId,
  runDetail,
  runDetailLoading,
}: {
  expandedRunId: string | null
  runDetail: AgentBenchmarkRunDetail | null
  runDetailLoading: boolean
}) {
  if (!expandedRunId) return null
  if (runDetailLoading) {
    return (
      <div className="mt-3 flex items-center justify-center py-4">
        <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
      </div>
    )
  }
  if (!runDetail) return null

  const failedAttempts = runDetail.attempts.filter((a) => !a.passed)
  const passedAttempts = runDetail.attempts.filter((a) => a.passed)

  return (
    <div className="mt-3 space-y-1.5">
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

export function RecentRunsCard({
  recentRuns,
  expandedRunId,
  runDetail,
  runDetailLoading,
  onRunClick,
  title = 'Recent runs',
}: RecentRunsCardProps) {
  return (
    <ChartCard title={title}>
      {recentRuns.length === 0 ? (
        <p className="text-sm text-slate-400">No persisted runs yet.</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {recentRuns.map((run) => {
            const isExpanded = expandedRunId === run.run_id
            return (
              <article
                key={run.run_id}
                onClick={() => onRunClick(run.run_id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') onRunClick(run.run_id)
                }}
                aria-expanded={isExpanded}
                className={`cursor-pointer rounded-2xl border px-4 py-4 transition-colors ${isExpanded ? 'border-amber-800 bg-amber-950/20' : 'border-slate-800 bg-slate-950/50 hover:border-slate-700'}`}
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
                  Models: {run.models.join(', ')}
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  Cases: {run.case_ids.join(', ')}
                </p>

                {isExpanded ? (
                  <RunDrillDown
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
