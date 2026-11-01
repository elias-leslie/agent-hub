'use client'

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { Suspense, useMemo, useState } from 'react'
import {
  type ContextDays,
  fetchMatrix,
  fetchTrend,
  type Trend,
  type TrendStep,
} from '@/lib/api/context-observability'
import { cn } from '@/lib/utils'
import { ContextHeader, RangeToggle } from '../components/ContextHeader'
import { EmptyNote, FailedNotice, Skeleton } from '../components/Notices'
import { PartsLegend } from '../components/TokenBar'
import { stepHeadline, TrendChart } from '../components/TrendChart'
import {
  ageDays,
  ago,
  CAUSE_META,
  cellHref,
  dayLabel,
  FLAG_MIN_STARTS,
  harnessLabel,
  LANE_NOTE,
  markerText,
  modelLabel,
  PART_COLOR,
  roleLabel,
  shortDate,
  shortDateTime,
  signedPct,
  signedTok,
  tok,
} from '../format'
import { useContextParams } from '../useContextParams'

const DEFAULTS = { days: 30 as ContextDays, harness: 'claude', role: 'lane' }

function Headline({ trend }: { trend: Trend }) {
  const h = trend.headline
  const covered =
    trend.coverage_from != null &&
    ageDays(trend.coverage_from) >= trend.days * 2
  return (
    <section className="panel-surface grid gap-4 p-4 sm:grid-cols-[auto_1fr] lg:p-5">
      <div>
        <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
          Median first turn, last {trend.days} days
        </p>
        <p className="mt-1 flex items-baseline gap-3">
          <span className="font-mono text-3xl font-semibold text-slate-50">
            {tok(h.total)}
          </span>
          <span
            className={cn(
              'font-mono text-sm',
              h.delta_pct == null
                ? 'text-slate-600'
                : h.delta_pct > 0
                  ? 'text-amber-300'
                  : h.delta_pct < 0
                    ? 'text-emerald-300'
                    : 'text-slate-500',
            )}
          >
            {signedPct(h.delta_pct)}
          </span>
        </p>
        <p className="mt-1 text-xs text-slate-400">
          {h.delta_pct == null
            ? h.prev_n < 3
              ? `No comparison: ${h.prev_n === 0 ? 'no' : `only ${h.prev_n}`} earlier starts on the same model${trend.coverage_from ? ` (starts of this role are recorded from ${shortDate(trend.coverage_from)})` : ''}.`
              : 'No comparison: too few starts in this window on the same model.'
            : `${signedTok(h.delta)} against the previous ${trend.days} days (${tok(h.prev_total)}, ${h.prev_n} starts)${covered ? '' : ', where the data reaches back'}.`}
        </p>
      </div>
      <dl className="grid grid-cols-3 gap-3 self-center text-xs sm:max-w-md">
        {(
          [
            ['Harness', h.harness_tokens, PART_COLOR.harness],
            ['Ours', h.ours, PART_COLOR.ours],
            ['Brief', h.brief, PART_COLOR.brief],
          ] as const
        ).map(([name, value, color]) => (
          <div key={name}>
            <dt className="flex items-center gap-1.5 text-slate-500">
              <span
                className="h-2 w-2 rounded-sm"
                style={{ background: color }}
              />
              {name}
            </dt>
            <dd className="font-mono text-base text-slate-100">{tok(value)}</dd>
          </div>
        ))}
        <div className="col-span-3 text-slate-500">
          {h.n} {h.n === 1 ? 'start' : 'starts'}
          {trend.warn_tokens != null && (
            <> · warn level {tok(trend.warn_tokens)}</>
          )}
          {trend.jump_pct != null && (
            <> · a step is a lasting move of {trend.jump_pct}% or more</>
          )}
        </div>
      </dl>
    </section>
  )
}

function Dips({ trend }: { trend: Trend }) {
  if (trend.dips.length === 0) return null
  return (
    <div className="mt-4 border-t border-slate-800/70 pt-3">
      <h4 className="text-xs font-semibold text-slate-300">
        Days that moved by {trend.jump_pct ?? '—'}% or more but are not steps
      </h4>
      <ul className="mt-2 space-y-2">
        {trend.dips.map((d) => (
          <li key={d.day} className="text-xs text-slate-400">
            <span className="font-mono text-slate-200">
              {dayLabel(d.day)} · {tok(d.before_total)} → {tok(d.total)} (
              {signedPct(d.pct)})
            </span>
            <span className="block">Not a step: {d.reason}.</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function StepList({
  trend,
  selected,
  onSelect,
}: {
  trend: Trend
  selected: string | null
  onSelect: (at: string | null) => void
}) {
  if (trend.steps.length === 0) {
    return (
      <>
        <EmptyNote>
          No step in this range. A step is a lasting move of{' '}
          {trend.jump_pct ?? '—'}% or more, with {FLAG_MIN_STARTS} or more
          starts on each side, so nothing is marked.
        </EmptyNote>
        <Dips trend={trend} />
      </>
    )
  }
  return (
    <>
      <ul className="space-y-2">
        {[...trend.steps].reverse().map((s: TrendStep) => {
          const meta = CAUSE_META[s.cause] ?? CAUSE_META.none
          const on = selected === s.at
          return (
            <li key={s.at}>
              <button
                type="button"
                aria-pressed={on}
                onClick={() => onSelect(on ? null : s.at)}
                className={cn(
                  'w-full rounded-xl border px-3 py-2.5 text-left transition-colors focus-ring-amber',
                  on
                    ? 'border-slate-500 bg-slate-800/70'
                    : 'border-slate-800/80 bg-slate-950/40 hover:border-slate-700',
                )}
              >
                <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span
                    className="inline-flex items-center gap-1.5 text-xs font-semibold"
                    style={{ color: meta.color }}
                  >
                    <span
                      className="h-2.5 w-2.5 rotate-45"
                      style={{ background: meta.color }}
                    />
                    {meta.label}
                  </span>
                  <span className="text-xs text-slate-400">
                    {shortDateTime(s.at)}
                  </span>
                  <span className="font-mono text-xs text-slate-200">
                    {stepHeadline(s)}
                  </span>
                </span>
                <span className="mt-1 block text-xs text-slate-400">
                  {s.summary}
                </span>
                {s.markers.length > 0 && (
                  <span className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
                    {s.markers.map((m) => (
                      <span key={`${m.kind}-${m.at}-${m.label}`}>
                        {markerText(m)}
                      </span>
                    ))}
                  </span>
                )}
              </button>
            </li>
          )
        })}
      </ul>
      <Dips trend={trend} />
    </>
  )
}

function ChartLegend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
      <PartsLegend />
      <span className="inline-flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-slate-300/60" />
        One start
      </span>
      {(['ours', 'config', 'harness_version'] as const).map((c) => (
        <span key={c} className="inline-flex items-center gap-1.5">
          <span
            className="h-2 w-2 rotate-45"
            style={{ background: CAUSE_META[c].color }}
          />
          Step: {CAUSE_META[c].label.toLowerCase()}
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5">
        <span className="h-3 border-l border-dashed border-violet-400" />
        New harness version
      </span>
    </div>
  )
}

function TrendView() {
  const { state, update } = useContextParams(DEFAULTS)
  const harness = state.harness ?? DEFAULTS.harness
  const role = state.role ?? DEFAULTS.role
  const [selected, setSelected] = useState<string | null>(null)
  const query = useQuery({
    queryKey: ['context-trend', harness, role, state.days],
    queryFn: () => fetchTrend(harness, role, state.days),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  })
  // The cell list for the selectors comes from the widest matrix, so a role seen only last month is still selectable.
  const options = useQuery({
    queryKey: ['context-matrix', 90],
    queryFn: () => fetchMatrix(90),
    staleTime: 5 * 60_000,
  })
  const harnesses = options.data?.harnesses.map((h) => h.harness) ?? [harness]
  const roles = useMemo(() => {
    const names = (options.data?.cells ?? [])
      .filter((c) => c.harness === harness)
      .map((c) => c.cell)
    return ['lane', ...new Set(names)].filter(
      (r, i, all) => all.indexOf(r) === i,
    )
  }, [options.data, harness])
  const data = query.data
  const stale =
    Boolean(data) && (data?.harness !== harness || data?.role !== role)
  const latestOld = data?.latest_at ? ageDays(data.latest_at) >= 3 : false

  return (
    <div className="page-shell context-scope">
      <div className="page-backdrop bg-grid-pattern opacity-60" />
      <ContextHeader
        controls={
          <>
            <select
              aria-label="Harness"
              className="control-select h-8 py-0 text-xs"
              value={harness}
              onChange={(e) =>
                update({ harness: e.target.value, role: 'lane' })
              }
            >
              {harnesses.map((h) => (
                <option key={h} value={h}>
                  {harnessLabel(h)}
                </option>
              ))}
            </select>
            <select
              aria-label="Role"
              className="control-select h-8 max-w-44 py-0 text-xs"
              value={role}
              onChange={(e) => update({ role: e.target.value })}
            >
              {roles.map((r) => (
                <option key={r} value={r}>
                  {roleLabel(r)}
                </option>
              ))}
            </select>
            <RangeToggle
              days={state.days}
              onChange={(days) => update({ days })}
            />
          </>
        }
      />
      <main className="page-frame">
        <div className="page-container space-y-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-semibold text-slate-100">
              {harnessLabel(harness)} · {roleLabel(role)}
              {data && (
                <Link
                  href={cellHref(harness, role)}
                  prefetch={false}
                  className="ml-3 text-xs font-normal text-amber-300 underline underline-offset-2 focus-ring-amber"
                >
                  Latest start and delivered blocks
                </Link>
              )}
            </h2>
            <span className="text-xs text-slate-500" aria-live="polite">
              {data
                ? `updated ${ago(data.generated_at)}${query.isFetching ? ' · refreshing' : ''}`
                : ''}
            </span>
          </div>

          {query.isError && (
            <FailedNotice
              what="the trend"
              error={query.error}
              hasData={Boolean(data)}
              updatedAt={query.dataUpdatedAt}
              onRetry={() => query.refetch()}
            />
          )}
          {!data && query.isLoading && (
            <div className="space-y-3" aria-busy="true" aria-label="Loading">
              <Skeleton className="h-28" />
              <Skeleton className="h-72" />
            </div>
          )}

          {data && (
            <div className={cn('space-y-4', stale && 'opacity-60')}>
              {data.points.length === 0 ? (
                <div className="panel-surface">
                  <EmptyNote>
                    No measured starts for {harnessLabel(harness)} ·{' '}
                    {roleLabel(role)} in the last {state.days} days.
                  </EmptyNote>
                </div>
              ) : (
                <>
                  {latestOld && data.latest_at && (
                    <p className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-2 text-xs text-amber-200">
                      The newest start here is {ago(data.latest_at)}; this cell
                      is stale.
                    </p>
                  )}
                  <Headline trend={data} />
                  <section className="panel-surface p-4 lg:p-5">
                    <div className="mb-3 space-y-2">
                      <h3 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                        First turn over time
                      </h3>
                      <ChartLegend />
                    </div>
                    <TrendChart
                      trend={data}
                      selected={selected}
                      onSelect={setSelected}
                    />
                    <p className="mt-2 text-xs text-slate-500">
                      Each shaded band is the day’s median of one part. Dots are
                      single starts, so the bands and dots can differ.{' '}
                      {data.points_total > data.points.length
                        ? `${data.points.length} of ${data.points_total} starts drawn.`
                        : `${data.points_total} starts.`}
                      {data.coverage_from &&
                      ageDays(data.coverage_from) < state.days
                        ? ` Starts of this role are recorded from ${shortDate(data.coverage_from)}.`
                        : ''}
                    </p>
                    {data.models.length > 1 && (
                      <p className="mt-1 text-xs text-slate-500">
                        These starts mix models (
                        {data.models
                          .slice(0, 3)
                          .map((m) => `${modelLabel(m.model)} ${m.n}`)
                          .join(', ')}
                        ). Steps compare one model at a time, so a dip on the
                        chart can be starts of a different model.
                      </p>
                    )}
                    {role === 'lane' && (
                      <p className="mt-1 text-xs text-slate-500">{LANE_NOTE}</p>
                    )}
                  </section>
                  <section className="panel-surface p-4 lg:p-5">
                    <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                      Steps and what moved
                    </h3>
                    <StepList
                      trend={data}
                      selected={selected}
                      onSelect={setSelected}
                    />
                  </section>
                </>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}

export default function ContextTrendPage() {
  return (
    <Suspense>
      <TrendView />
    </Suspense>
  )
}
