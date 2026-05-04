'use client'

import { FlaskConical } from 'lucide-react'
import Link from 'next/link'

import type { ArenaAgentSummary } from '@/app/arena/types'
import {
  deriveArenaStatusFromBenchmark,
  formatPercent,
  formatRelativeTime,
  formatScore,
  summarizeArenaIssue,
} from '../utils'

interface ArenaAgentCardProps {
  agent: ArenaAgentSummary
}

export function ArenaAgentCard({ agent }: ArenaAgentCardProps) {
  const status = deriveArenaStatusFromBenchmark(agent.benchmark)
  const hasHistory = agent.benchmark.total_runs > 0
  const signalCount = agent.signal_volume
    ? agent.signal_volume.friction +
      agent.signal_volume.improvement +
      agent.signal_volume.idea +
      agent.signal_volume.praise
    : 0

  return (
    <Link
      href={`/arena/${agent.slug}`}
      prefetch={false}
      className="group relative flex flex-col rounded-2xl border border-slate-800 bg-slate-900/90 p-5 transition-all hover:border-amber-800 hover:shadow-md hover:shadow-amber-950/20"
    >
      <div className="pointer-events-none absolute inset-0 rounded-2xl opacity-0 transition-opacity group-hover:opacity-100 bg-[radial-gradient(circle_at_top_left,oklch(0.75_0.18_55_/_0.04),transparent_50%)]" />

      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-amber-500" />
            <h3 className="truncate text-sm font-semibold text-slate-100">
              {agent.name}
            </h3>
          </div>
          <p className="mt-1 text-[11px] font-mono text-slate-500">
            {agent.slug}
          </p>
        </div>
        <span
          className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold ${status.tone}`}
        >
          {status.label}
        </span>
      </div>

      {hasHistory ? (
        <>
          {/* Score bar */}
          <div className="relative mt-4">
            <div className="flex items-baseline justify-between mb-1.5">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">
                Score
              </span>
              <span className="text-sm font-semibold tabular-nums text-slate-100">
                {formatScore(agent.benchmark.avg_score)}
              </span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-slate-800">
              <div
                className="h-1.5 rounded-full bg-gradient-to-r from-amber-600 to-amber-400 transition-all duration-500"
                style={{
                  width: `${Math.min(100, agent.benchmark.avg_score ?? 0)}%`,
                }}
              />
            </div>
          </div>

          <dl className="relative mt-3 grid grid-cols-3 gap-2 text-sm">
            <div className="rounded-lg bg-slate-800/50 px-2.5 py-2 text-center">
              <dd className="text-sm font-semibold tabular-nums text-slate-100">
                {formatPercent(agent.benchmark.pass_rate)}
              </dd>
              <dt className="mt-0.5 text-[10px] text-slate-500">Pass</dt>
            </div>
            <div className="rounded-lg bg-slate-800/50 px-2.5 py-2 text-center">
              <dd className="text-sm font-semibold tabular-nums text-slate-100">
                {agent.benchmark.total_runs}
              </dd>
              <dt className="mt-0.5 text-[10px] text-slate-500">Runs</dt>
            </div>
            <div className="rounded-lg bg-slate-800/50 px-2.5 py-2 text-center">
              <dd
                className={`text-sm font-semibold tabular-nums ${agent.benchmark.open_regressions > 0 ? 'text-rose-400' : 'text-slate-100'}`}
              >
                {agent.benchmark.open_regressions}
              </dd>
              <dt className="mt-0.5 text-[10px] text-slate-500">Regress</dt>
            </div>
          </dl>

          <div className="relative mt-3 flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className="rounded-full bg-slate-800 px-2 py-0.5 text-slate-300 ring-1 ring-slate-700">
              {formatRelativeTime(agent.benchmark.latest_completed_at)}
            </span>
            {signalCount > 0 ? (
              <span className="rounded-full bg-amber-950/30 px-2 py-0.5 text-amber-200 ring-1 ring-amber-900">
                {signalCount} signals
              </span>
            ) : null}
          </div>
          {agent.top_issue ? (
            <p
              className="relative mt-2.5 line-clamp-2 text-xs leading-relaxed text-slate-400"
              title={agent.top_issue.content}
            >
              {summarizeArenaIssue(agent.top_issue.content, 120)}
            </p>
          ) : null}
        </>
      ) : (
        <>
          <div className="relative mt-4 rounded-lg border border-dashed border-slate-700 bg-slate-800/20 px-3 py-4 text-center">
            <p className="text-sm text-slate-400">No benchmark history</p>
            <p className="mt-1 text-[11px] text-slate-500">
              Run Arena to generate evidence
            </p>
          </div>
          {agent.top_issue ? (
            <p
              className="relative mt-3 line-clamp-2 text-xs text-slate-400"
              title={agent.top_issue.content}
            >
              {summarizeArenaIssue(agent.top_issue.content, 120)}
            </p>
          ) : null}
        </>
      )}
    </Link>
  )
}
