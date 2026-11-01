'use client'

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Flag } from 'lucide-react'
import Link from 'next/link'
import { Suspense, useMemo } from 'react'
import {
  fetchMatrix,
  type Matrix,
  type MatrixCell,
} from '@/lib/api/context-observability'
import { cn } from '@/lib/utils'
import { ContextHeader, RangeToggle } from './components/ContextHeader'
import { EmptyNote, FailedNotice, Skeleton } from './components/Notices'
import { PartsLegend, TokenBar } from './components/TokenBar'
import {
  ageDays,
  ago,
  type CellGroup,
  cellGroup,
  cellHref,
  FEW_STARTS,
  flagText,
  GROUP_LABEL,
  harnessLabel,
  isStale,
  roleLabel,
  shortDate,
  signedPct,
  tok,
  trendHref,
} from './format'
import { useContextParams } from './useContextParams'

const DEFAULT_DAYS = 7
const GROUPS: CellGroup[] = ['roles', 'other', 'subagents']

function DeltaChip({ cell, days }: { cell: MatrixCell; days: number }) {
  if (cell.delta_pct == null) {
    return (
      <span
        className="font-mono text-[11px] text-slate-600"
        title={`No change shown: fewer than ${FEW_STARTS} starts in this or the previous ${days} days`}
      >
        —
      </span>
    )
  }
  const up = cell.delta_pct > 0
  return (
    <span
      className={cn(
        'font-mono text-[11px]',
        Math.round(cell.delta_pct) === 0
          ? 'text-slate-500'
          : up
            ? 'text-amber-300'
            : 'text-emerald-300',
      )}
      title={`Against the previous ${days} days: ${tok(cell.prev_total)} (${cell.prev_n} starts)`}
    >
      {signedPct(cell.delta_pct)}
    </span>
  )
}

function MatrixCellView({
  cell,
  scale,
  days,
  showHarness,
}: {
  cell: MatrixCell
  scale: number
  days: number
  showHarness: boolean
}) {
  const flag = flagText(cell)
  const stale = isStale(cell)
  return (
    <Link
      href={cellHref(cell.harness, cell.cell)}
      prefetch={false}
      className={cn(
        'block rounded-lg border px-2.5 py-2 transition-colors focus-ring-amber',
        flag
          ? 'border-amber-500/40 bg-amber-500/5 hover:bg-amber-500/10'
          : 'border-slate-800/80 bg-slate-950/40 hover:border-slate-700 hover:bg-slate-900/80',
      )}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="flex min-w-0 items-baseline gap-1.5">
          {showHarness && (
            <span className="truncate text-[11px] text-slate-500 sm:hidden">
              {harnessLabel(cell.harness)}
            </span>
          )}
          <span className="font-mono text-base font-semibold text-slate-100">
            {tok(cell.total)}
          </span>
        </span>
        <span className="flex items-center gap-1.5">
          {flag && (
            <span
              className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-300"
              title={flag}
            >
              <Flag className="h-3 w-3" aria-hidden="true" />
              {cell.flag === 'warn' ? 'over budget' : 'jumped'}
            </span>
          )}
          <DeltaChip cell={cell} days={days} />
        </span>
      </div>
      <TokenBar
        className="mt-1.5"
        total={cell.total}
        harness={cell.harness_tokens}
        ours={cell.ours}
        brief={cell.brief}
        scale={scale}
      />
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 text-[11px] text-slate-500">
        <span
          className={cn(cell.n < FEW_STARTS && 'text-amber-300/80')}
          title={
            cell.n < FEW_STARTS
              ? 'Few starts: treat the median loosely'
              : undefined
          }
        >
          n={cell.n}
        </span>
        <span>{cell.version ?? '—'}</span>
        {stale && (
          <span
            className="text-amber-300/80"
            title={`Last start ${ago(cell.latest_at)}`}
          >
            stale {ageDays(cell.latest_at)}d
          </span>
        )}
      </div>
    </Link>
  )
}

function MissingCell({ harness }: { harness: string }) {
  return (
    <div
      className="flex items-center gap-2 rounded-lg border border-dashed border-slate-800/70 px-2.5 py-2 text-slate-600 max-sm:hidden"
      title={`${harnessLabel(harness)} has no measured start for this role in the range`}
    >
      <span className="font-mono text-base">—</span>
    </div>
  )
}

function GroupTable({
  title,
  cells,
  harnesses,
  scale,
  days,
}: {
  title: string
  cells: MatrixCell[]
  harnesses: string[]
  scale: number
  days: number
}) {
  const roles = useMemo(() => {
    const byRole = new Map<string, MatrixCell[]>()
    for (const c of cells)
      byRole.set(c.cell, [...(byRole.get(c.cell) ?? []), c])
    return [...byRole.entries()].sort(
      (a, b) =>
        b[1].reduce((s, c) => s + c.n, 0) - a[1].reduce((s, c) => s + c.n, 0),
    )
  }, [cells])
  if (roles.length === 0) return null
  const colsStyle = {
    '--cols': `minmax(9rem,12rem) repeat(${harnesses.length}, minmax(0, 1fr))`,
  } as React.CSSProperties
  const cols = 'sm:[grid-template-columns:var(--cols)]'
  return (
    <section className="panel-surface p-4 lg:p-5">
      <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
        {title}
      </h2>
      <div
        className={cn(
          'hidden gap-2 pb-1 text-[11px] text-slate-500 sm:grid',
          cols,
        )}
        style={colsStyle}
        aria-hidden="true"
      >
        <span />
        {harnesses.map((h) => (
          <span key={h}>{harnessLabel(h)}</span>
        ))}
      </div>
      <ul className="space-y-2">
        {roles.map(([role, items]) => (
          <li
            key={role}
            className={cn('grid gap-2 sm:items-center', cols)}
            style={colsStyle}
          >
            <p className="text-sm font-medium text-slate-200">
              {roleLabel(role)}
            </p>
            {harnesses.map((h) => {
              const cell = items.find((c) => c.harness === h)
              return cell ? (
                <MatrixCellView
                  key={h}
                  cell={cell}
                  scale={scale}
                  days={days}
                  showHarness
                />
              ) : (
                <MissingCell key={h} harness={h} />
              )
            })}
          </li>
        ))}
      </ul>
    </section>
  )
}

function AgentList({
  cells,
  scale,
  days,
}: {
  cells: MatrixCell[]
  scale: number
  days: number
}) {
  if (cells.length === 0) return null
  return (
    <details className="panel-surface p-4 lg:p-5">
      <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 focus-ring-amber">
        {GROUP_LABEL.agents} ({cells.length})
      </summary>
      <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {cells.map((c) => (
          <li key={c.cell}>
            <p className="mb-1 truncate text-xs text-slate-300">
              {roleLabel(c.cell)}
            </p>
            <MatrixCellView
              cell={c}
              scale={scale}
              days={days}
              showHarness={false}
            />
          </li>
        ))}
      </ul>
    </details>
  )
}

function Summary({ data, cells }: { data: Matrix; cells: MatrixCell[] }) {
  const flagged = cells.filter((c) => c.flag)
  const young =
    data.coverage_from != null && ageDays(data.coverage_from) < data.days * 2
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        {flagged.length > 0 ? (
          <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1 text-amber-300">
            <Flag className="h-4 w-4" aria-hidden="true" />
            {flagged.length} over budget:
            {flagged.map((c) => (
              <Link
                key={`${c.harness}/${c.cell}`}
                href={cellHref(c.harness, c.cell)}
                prefetch={false}
                title={flagText(c) ?? undefined}
                className="underline underline-offset-2 focus-ring-amber"
              >
                {harnessLabel(c.harness)} {roleLabel(c.cell)}
              </Link>
            ))}
          </span>
        ) : (
          <span className="text-slate-400">
            Nothing over budget in the last 24 hours.
          </span>
        )}
        <Link
          href="/context/changes"
          prefetch={false}
          className="text-amber-300 underline underline-offset-2 focus-ring-amber"
        >
          Review context changes
        </Link>
      </div>
      {young && data.coverage_from && (
        <p className="text-xs text-slate-500">
          Measured starts begin {shortDate(data.coverage_from)}, so the change
          against the previous {data.days} days is empty or thin where it would
          reach further back.
        </p>
      )}
    </div>
  )
}

function CostView() {
  const { state, update } = useContextParams({ days: DEFAULT_DAYS })
  const query = useQuery({
    queryKey: ['context-matrix', state.days],
    queryFn: () => fetchMatrix(state.days),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  })
  const data = query.data
  const cells = useMemo(
    () =>
      (data?.cells ?? []).filter(
        (c) =>
          (!state.harness || c.harness === state.harness) &&
          (!state.role || c.cell === state.role),
      ),
    [data, state.harness, state.role],
  )
  const scale = Math.max(0, ...cells.map((c) => c.total ?? 0))
  const harnessOptions = data?.harnesses.map((h) => h.harness) ?? []
  const roleOptions = useMemo(
    () => [...new Set((data?.cells ?? []).map((c) => c.cell))].sort(),
    [data],
  )
  const matrixHarnesses = (data?.harnesses ?? [])
    .filter((h) => h.harness !== 'agent_hub')
    .filter((h) => !state.harness || h.harness === state.harness)
  const grouped = (group: CellGroup) =>
    cells.filter(
      (c) => cellGroup(c.cell) === group && c.harness !== 'agent_hub',
    )
  const agentCells = cells.filter((c) => cellGroup(c.cell) === 'agents')
  const claude = data?.harnesses.find((h) => h.harness === 'claude')

  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />
      <ContextHeader
        controls={
          <>
            <select
              aria-label="Harness"
              className="control-select h-8 py-0 text-xs"
              value={state.harness ?? ''}
              onChange={(e) => update({ harness: e.target.value || null })}
            >
              <option value="">All harnesses</option>
              {harnessOptions.map((h) => (
                <option key={h} value={h}>
                  {harnessLabel(h)}
                </option>
              ))}
            </select>
            <select
              aria-label="Role"
              className="control-select h-8 max-w-44 py-0 text-xs"
              value={state.role ?? ''}
              onChange={(e) => update({ role: e.target.value || null })}
            >
              <option value="">All roles</option>
              {roleOptions.map((r) => (
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
            <p className="max-w-3xl text-xs text-slate-400">
              Median first turn of each start in the last {state.days} days:
              everything in front of the model before the brief, split into what
              the harness adds and what we deliver.{' '}
              <span className="text-slate-500">
                Antigravity is not measured yet.
              </span>
            </p>
            <span className="text-xs text-slate-500" aria-live="polite">
              {data
                ? `updated ${ago(data.generated_at)}${query.isFetching ? ' · refreshing' : ''}`
                : ''}
            </span>
          </div>

          {query.isError && (
            <FailedNotice
              what="the context matrix"
              error={query.error}
              hasData={Boolean(data)}
              updatedAt={query.dataUpdatedAt}
              onRetry={() => query.refetch()}
            />
          )}

          {!data && query.isLoading && (
            <div className="space-y-3" aria-busy="true" aria-label="Loading">
              <Skeleton className="h-8" />
              <Skeleton className="h-64" />
            </div>
          )}

          {data && (
            <>
              <Summary data={data} cells={cells} />
              <PartsLegend />
              {cells.length === 0 ? (
                <div className="panel-surface">
                  <EmptyNote>
                    {data.cells.length === 0
                      ? `No measured starts in the last ${state.days} days.`
                      : 'No starts match these filters in this range.'}
                  </EmptyNote>
                </div>
              ) : (
                <>
                  {GROUPS.map((g) => (
                    <GroupTable
                      key={g}
                      title={GROUP_LABEL[g]}
                      cells={grouped(g)}
                      harnesses={matrixHarnesses
                        .map((h) => h.harness)
                        .filter((h) => grouped(g).some((c) => c.harness === h))}
                      scale={scale}
                      days={state.days}
                    />
                  ))}
                  <AgentList
                    cells={agentCells}
                    scale={scale}
                    days={state.days}
                  />
                </>
              )}
              {matrixHarnesses.length > 0 && (
                <p className="text-xs text-slate-500">
                  Versions now:{' '}
                  {matrixHarnesses
                    .map(
                      (h) => `${harnessLabel(h.harness)} ${h.version ?? '—'}`,
                    )
                    .join(' · ')}
                  .{' '}
                  {claude && (
                    <Link
                      href={trendHref('claude', 'lane', state.days)}
                      prefetch={false}
                      className="text-amber-300 underline underline-offset-2 focus-ring-amber"
                    >
                      See how Claude lanes moved
                    </Link>
                  )}
                </p>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  )
}

export default function ContextCostPage() {
  return (
    <Suspense>
      <CostView />
    </Suspense>
  )
}
