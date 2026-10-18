'use client'

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { CircleDollarSign, X } from 'lucide-react'
import { Suspense, useCallback } from 'react'
import {
  fetchSpend,
  type SpendKind,
  type SpendOverview,
} from '@/lib/api/analytics'
import { cn } from '@/lib/utils'
import { CostTable } from './components/CostTable'
import { ItemDrawer } from './components/ItemDrawer'
import { PlansSection } from './components/PlansSection'
import { SpendChart } from './components/SpendChart'
import { SpendSummary } from './components/SpendSummary'
import {
  bucketSpan,
  KIND_META,
  KIND_ORDER,
  RANGE_DAYS,
  RANGE_LABEL,
  SOURCE_LABEL,
  usd,
} from './format'
import { RANGES, useCostsState } from './hooks/useCostsState'

function CoverageLine({ data }: { data: SpendOverview }) {
  const { coverage, unpriced_calls: unpriced } = data
  const parts: string[] = []
  if (coverage.percent == null) {
    parts.push(`No agent sessions in the ${RANGE_LABEL[data.range]}.`)
  } else {
    let line = `Usage captured for ${coverage.percent}% of agent work in the ${RANGE_LABEL[data.range]}`
    if (coverage.uncaptured.length > 0) {
      const missing = coverage.uncaptured
        .map(
          (g) =>
            `${g.sessions} ${SOURCE_LABEL[g.source] ?? g.source} ${g.sessions === 1 ? 'session' : 'sessions'}`,
        )
        .join(', ')
      line += `; no usage recorded for ${missing}`
    }
    parts.push(`${line}.`)
  }
  if (unpriced > 0) {
    parts.push(
      `${unpriced.toLocaleString()} ${unpriced === 1 ? 'call' : 'calls'} used a model with no list price and count as $0.`,
    )
  }
  return <p className="text-xs text-slate-500">{parts.join(' ')}</p>
}

function Legend({ data }: { data: SpendOverview }) {
  const totals = Object.fromEntries(
    KIND_ORDER.map((k) => [
      k,
      data.chart.reduce((sum, bar) => sum + bar[k], 0),
    ]),
  ) as Record<SpendKind, number>
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
      {KIND_ORDER.map((k) => (
        <span
          key={k}
          className="inline-flex items-center gap-1.5"
          title={KIND_META[k].hint}
        >
          <span className={cn('h-2 w-2 rounded-sm', KIND_META[k].dot)} />
          {KIND_META[k].label}
          <span className="font-mono text-slate-300">{usd(totals[k])}</span>
        </span>
      ))}
    </div>
  )
}

function Chip({
  active,
  onClick,
  children,
  title,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
  title?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className={cn(
        'rounded-full border px-3 py-1 text-xs transition-colors',
        active
          ? 'border-amber-500 bg-amber-500 font-semibold text-slate-950'
          : 'border-slate-800 bg-slate-900/60 text-slate-400 hover:text-slate-200',
      )}
    >
      {children}
    </button>
  )
}

function CostsView() {
  const { state, update } = useCostsState()
  const filters = {
    kind: state.kind,
    project: state.project,
    model: state.model,
  }
  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ['spend', state.range, filters, state.bucket],
    queryFn: () => fetchSpend(state.range, filters, state.bucket),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  })
  const closeItem = useCallback(() => update({ item: null }), [update])
  const narrowed = Boolean(
    state.kind || state.project || state.model || state.bucket,
  )

  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />
      <header className="page-header">
        <div className="page-container px-4 lg:px-8">
          <div className="page-header-row">
            <div className="page-title-group">
              <div className="page-title-icon">
                <CircleDollarSign className="h-5 w-5" />
              </div>
              <div className="page-title-stack">
                <h1 className="page-title">Costs</h1>
                <div className="page-meta">
                  <span>
                    What agent work would cost at API list prices, subscription
                    use included.
                  </span>
                </div>
              </div>
            </div>
            <div
              className="rounded-2xl border border-slate-800/80 bg-slate-900/80 p-1"
              role="group"
              aria-label="Time range"
            >
              <div className="flex items-center gap-1">
                {RANGES.map((r) => (
                  <button
                    key={r}
                    type="button"
                    aria-pressed={state.range === r}
                    onClick={() => update({ range: r })}
                    className={cn(
                      'rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors',
                      state.range === r
                        ? 'bg-amber-500 text-slate-950'
                        : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100',
                    )}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="page-frame">
        <div className="page-container space-y-5">
          <SpendSummary summary={data?.summary} loading={isLoading} />
          {data && <CoverageLine data={data} />}

          {error && !data ? (
            <div className="panel-surface p-5 text-sm text-red-400">
              Couldn't load spend:{' '}
              {error instanceof Error ? error.message : 'unknown error'}
            </div>
          ) : (
            <>
              <section className="panel-surface p-4 lg:p-5">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                    Spend, {RANGE_LABEL[state.range]}
                  </h2>
                  {data && <Legend data={data} />}
                </div>
                {isLoading || !data ? (
                  <div className="h-52 animate-pulse rounded-xl bg-slate-800/40 sm:h-60" />
                ) : (
                  <SpendChart
                    bars={data.chart}
                    range={state.range}
                    selected={state.bucket}
                    onSelect={(bucket) => update({ bucket })}
                  />
                )}
              </section>

              <section className="panel-surface p-4 lg:p-5">
                <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                  <h2 className="text-sm font-semibold text-slate-100">
                    What's costing the most
                  </h2>
                  {data && (
                    <span className="text-xs text-slate-500">
                      {usd(data.total_usd)} across{' '}
                      {data.item_count.toLocaleString()}{' '}
                      {data.item_count === 1 ? 'item' : 'items'}
                      {data.item_count > data.items.length &&
                        `, top ${data.items.length} shown`}
                      {isFetching && ' · updating'}
                    </span>
                  )}
                </div>

                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <Chip
                    active={!state.kind}
                    onClick={() => update({ kind: null })}
                  >
                    All kinds
                  </Chip>
                  {KIND_ORDER.map((k) => (
                    <Chip
                      key={k}
                      active={state.kind === k}
                      title={KIND_META[k].hint}
                      onClick={() =>
                        update({ kind: state.kind === k ? null : k })
                      }
                    >
                      {KIND_META[k].label}
                    </Chip>
                  ))}
                  <select
                    aria-label="Project"
                    className="control-select h-7 py-0 text-xs"
                    value={state.project ?? ''}
                    onChange={(e) =>
                      update({ project: e.target.value || null })
                    }
                  >
                    <option value="">All projects</option>
                    {data?.filters.project.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="Model"
                    className="control-select h-7 py-0 text-xs"
                    value={state.model ?? ''}
                    onChange={(e) => update({ model: e.target.value || null })}
                  >
                    <option value="">All models</option>
                    {data?.filters.model.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                  {state.bucket && data && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-sky-500/30 bg-sky-500/10 px-3 py-1 text-xs text-sky-200">
                      {bucketSpan(
                        state.bucket,
                        data.bucket_seconds,
                        state.range,
                      )}
                      <button
                        type="button"
                        aria-label="Show the whole range"
                        onClick={() => update({ bucket: null })}
                        className="rounded-full hover:text-white"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  )}
                  {narrowed && (
                    <button
                      type="button"
                      onClick={() =>
                        update({
                          kind: null,
                          project: null,
                          model: null,
                          bucket: null,
                        })
                      }
                      className="text-xs text-slate-500 underline-offset-2 hover:text-slate-300 hover:underline"
                    >
                      Clear filters
                    </button>
                  )}
                </div>

                {isLoading || !data ? (
                  <div className="space-y-2">
                    {[0, 1, 2, 3, 4].map((i) => (
                      <div
                        key={i}
                        className="h-9 animate-pulse rounded-lg bg-slate-800/40"
                      />
                    ))}
                  </div>
                ) : data.items.length === 0 ? (
                  <p className="py-6 text-center text-sm text-slate-500">
                    {narrowed
                      ? 'Nothing matches these filters in this range.'
                      : `No agent spend in the ${RANGE_LABEL[state.range]}.`}
                  </p>
                ) : (
                  <CostTable
                    items={data.items}
                    selected={state.item}
                    onOpen={(item) => update({ item })}
                  />
                )}
              </section>
            </>
          )}

          <PlansSection daysRange={RANGE_DAYS[state.range]} />
        </div>
      </main>

      {state.item && (
        <ItemDrawer
          itemKey={state.item}
          range={state.range}
          onClose={closeItem}
        />
      )}
    </div>
  )
}

export default function CostsPage() {
  return (
    <Suspense>
      <CostsView />
    </Suspense>
  )
}
