import { ChartCard } from '@/app/agents/[slug]/analytics/components/ChartCard'
import type { AgentRegressionClusterSummary } from '@/app/agents/[slug]/analytics/types'
import { formatArenaLabel } from '@/app/arena/utils'

interface RegressionWatchlistProps {
  regressions: AgentRegressionClusterSummary[]
}

export function RegressionWatchlist({ regressions }: RegressionWatchlistProps) {
  return (
    <ChartCard title="Regression watchlist">
      {regressions.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-emerald-900 bg-emerald-950/20 px-5 py-8 text-center">
          <p className="text-sm font-semibold text-slate-100">
            No open regression clusters
          </p>
          <p className="mt-2 text-sm text-slate-400">
            Arena is currently tracking clean recent benchmark history for this
            agent.
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
                {formatArenaLabel(regression.suite_id)} · models{' '}
                {regression.affected_models.join(', ')}
              </p>
            </article>
          ))}
        </div>
      )}
    </ChartCard>
  )
}
