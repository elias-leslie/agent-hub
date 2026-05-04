import { FlaskConical, Orbit, Sparkles } from 'lucide-react'
import Link from 'next/link'
import { formatPercent, formatScore } from '@/app/arena/utils'
import type { AgentBenchmarkDashboard } from '../types'
import { ChartCard } from './ChartCard'

interface ArenaPreviewCardProps {
  dashboard: AgentBenchmarkDashboard
  slug: string
  ctaLabel?: string | null
  compact?: boolean
}

export function ArenaPreviewCard({
  dashboard,
  slug,
  ctaLabel = 'Open Arena',
  compact = true,
}: ArenaPreviewCardProps) {
  const hasHistory = dashboard.overview.total_runs > 0
  const recentSuites = new Set(dashboard.recent_runs.map((run) => run.suite_id))
    .size

  return (
    <ChartCard title="Arena">
      <div className="relative overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,oklch(0.75_0.18_55_/_0.08),transparent_38%),radial-gradient(circle_at_bottom_right,oklch(0.7_0.17_155_/_0.06),transparent_34%)]" />
        <div className="relative">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full bg-amber-950/60 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-200">
                <FlaskConical className="h-3.5 w-3.5" />
                Evaluation lab
              </div>
              <p className="mt-3 text-sm font-semibold text-slate-100">
                {hasHistory
                  ? 'Arena has fresh evidence for this agent.'
                  : 'Arena is ready for the first benchmark battery.'}
              </p>
              <p className="mt-1 max-w-2xl text-sm text-slate-300">
                {hasHistory
                  ? 'Use Arena for score trends, experiments, regressions, and model comparisons without crowding runtime analytics.'
                  : 'Run a benchmark or honing loop and Arena will turn the results into a readable scoreboard instead of raw logs.'}
              </p>
            </div>
            <Sparkles className="h-5 w-5 text-amber-500" />
          </div>

          <div
            className={`mt-4 grid gap-3 ${compact ? 'md:grid-cols-4' : 'md:grid-cols-2 xl:grid-cols-4'}`}
          >
            <div className="rounded-xl bg-slate-900/90 px-3 py-3 ring-1 ring-slate-800">
              <p className="text-xs uppercase tracking-wide text-slate-400">
                Runs
              </p>
              <p className="mt-1 text-xl font-semibold text-slate-50">
                {dashboard.overview.total_runs}
              </p>
            </div>
            <div className="rounded-xl bg-slate-900/90 px-3 py-3 ring-1 ring-slate-800">
              <p className="text-xs uppercase tracking-wide text-slate-400">
                Avg score
              </p>
              <p className="mt-1 text-xl font-semibold text-slate-50">
                {formatScore(dashboard.overview.avg_score)}
              </p>
            </div>
            <div className="rounded-xl bg-slate-900/90 px-3 py-3 ring-1 ring-slate-800">
              <p className="text-xs uppercase tracking-wide text-slate-400">
                Pass rate
              </p>
              <p className="mt-1 text-xl font-semibold text-slate-50">
                {formatPercent(dashboard.overview.pass_rate)}
              </p>
            </div>
            <div className="rounded-xl bg-slate-900/90 px-3 py-3 ring-1 ring-slate-800">
              <p className="text-xs uppercase tracking-wide text-slate-400">
                Suites
              </p>
              <p className="mt-1 inline-flex items-center gap-2 text-xl font-semibold text-slate-50">
                <Orbit className="h-4 w-4 text-amber-500" />
                {recentSuites}
              </p>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <div className="text-xs text-slate-400">
              Open regressions: {dashboard.overview.open_regressions} · Tracked
              models: {dashboard.overview.tracked_models.length}
            </div>
            {ctaLabel ? (
              <Link
                href={`/arena/${slug}`}
                className="inline-flex items-center gap-2 rounded-xl bg-slate-800 px-4 py-2 text-sm font-medium text-slate-100 transition-colors hover:bg-slate-700"
              >
                {ctaLabel}
              </Link>
            ) : null}
          </div>
        </div>
      </div>
    </ChartCard>
  )
}
