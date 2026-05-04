import { ChartCard } from '@/app/agents/[slug]/analytics/components/ChartCard'
import type {
  AgentBenchmarkCaseSummary,
  AgentBenchmarkSuiteSummary,
} from '@/app/agents/[slug]/analytics/types'
import {
  formatArenaLabel,
  formatPercent,
  formatRelativeTime,
  formatScore,
} from '@/app/arena/utils'

interface SuitePanelsProps {
  sortedSuites: AgentBenchmarkSuiteSummary[]
  sortedCases: AgentBenchmarkCaseSummary[]
}

export function SuitePanels({ sortedSuites, sortedCases }: SuitePanelsProps) {
  return (
    <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[1.1fr_0.9fr]">
      <ChartCard title="Suite board">
        {sortedSuites.length === 0 ? (
          <p className="text-sm text-slate-400">
            No suite history yet. Arena needs a benchmark battery before it can
            score stability by suite.
          </p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {sortedSuites.map((suite) => {
              const hasIssues =
                suite.open_regressions > 0 || (suite.avg_score ?? 100) < 90
              const tone = hasIssues
                ? 'border-amber-900 bg-amber-950/20'
                : 'border-emerald-900 bg-emerald-950/20'
              const badgeTone =
                suite.open_regressions > 0
                  ? 'bg-rose-950/30 text-rose-300 ring-rose-900'
                  : 'bg-emerald-950/30 text-emerald-300 ring-emerald-900'

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
                        {suite.run_count} runs · {suite.case_ids.length} cases ·{' '}
                        {suite.run_kinds.join(', ') || 'benchmark'}
                      </p>
                    </div>
                    <span
                      className={`rounded-full px-2 py-1 text-[11px] font-semibold ring-1 ${badgeTone}`}
                    >
                      {suite.open_regressions > 0
                        ? `${suite.open_regressions} regressions`
                        : 'stable'}
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
                    Models: {suite.tracked_models.join(', ') || 'Pending'}
                  </p>
                </article>
              )
            })}
          </div>
        )}
      </ChartCard>

      <ChartCard title="Case watchlist">
        {sortedCases.length === 0 ? (
          <p className="text-sm text-slate-400">
            No case-level evidence yet. Once attempts are persisted, Arena will
            rank brittle cases here.
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
                      {caseSummary.suite_ids
                        .map((suiteId) => formatArenaLabel(suiteId))
                        .join(', ')}{' '}
                      · {caseSummary.attempts} attempts
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
  )
}
