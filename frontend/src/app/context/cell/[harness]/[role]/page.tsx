'use client'

import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Flag } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { Suspense } from 'react'
import {
  type CellBlock,
  type CellView,
  fetchCell,
} from '@/lib/api/context-observability'
import { cn } from '@/lib/utils'
import { ContextHeader } from '../../../components/ContextHeader'
import { EmptyNote, FailedNotice, Skeleton } from '../../../components/Notices'
import { PartsLegend, TokenBar } from '../../../components/TokenBar'
import {
  ageDays,
  ago,
  CAUSE_META,
  harnessLabel,
  roleLabel,
  shortDateTime,
  shortRevision,
  signedPct,
  signedTok,
  tok,
  trendHref,
} from '../../../format'

const PART_ROWS: Array<{
  key: string
  label: string
  group: string
  hint?: string
}> = [
  {
    key: 'harness_core',
    label: 'Core prompt',
    group: 'Harness',
    hint: "The harness's own system prompt",
  },
  { key: 'harness_tools', label: 'Tool definitions', group: 'Harness' },
  {
    key: 'our_listings',
    label: 'Our listings',
    group: 'Harness',
    hint: 'Skill, agent and MCP listings our config adds',
  },
  {
    key: 'ah_global',
    label: 'Global',
    group: 'Ours',
    hint: 'Memories and prompts delivered to everyone',
  },
  { key: 'ah_role', label: 'Role', group: 'Ours' },
  { key: 'ah_project', label: 'Project', group: 'Ours' },
  { key: 'brief', label: 'First message', group: 'Brief' },
]

const METHOD_HINT: Record<string, string> = {
  exact: 'Counted by the provider',
  ratio: 'Split from the remainder by text length',
  derived: 'Total minus the parts measured',
  estimate: 'Estimated from characters (4 per token)',
  unknown: 'Not measured',
}

function Parts({ cell }: { cell: CellView }) {
  const rows = PART_ROWS.filter((r) => r.key in cell.parts)
  if (rows.length === 0) {
    return <EmptyNote>The split of this start was not measured.</EmptyNote>
  }
  const total = cell.latest?.total ?? 0
  return (
    <ul className="divide-y divide-slate-800/70">
      {rows.map((r) => {
        const part = cell.parts[r.key]
        const method = part.method ?? 'unknown'
        return (
          <li
            key={r.key}
            className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 py-2 sm:grid-cols-[6rem_1fr_5rem_8rem]"
          >
            <span className="text-xs text-slate-500 max-sm:hidden">
              {r.group}
            </span>
            <span className="text-sm text-slate-200" title={r.hint}>
              {r.label}
            </span>
            <span className="text-right font-mono text-sm text-slate-100">
              {tok(part.tokens)}
            </span>
            <span
              className="col-span-2 text-[11px] text-slate-500 sm:col-span-1 sm:text-right"
              title={METHOD_HINT[method]}
            >
              {part.tokens == null
                ? 'not measured'
                : total > 0
                  ? `${Math.round((part.tokens / total) * 100)}% · ${method}`
                  : method}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

function Writer({ block }: { block: CellBlock }) {
  if (!block.writer_at) {
    return <span title="No revision in the last 30 days">—</span>
  }
  const who = block.writer_session ?? block.writer_kind ?? 'unknown writer'
  return (
    <span
      title={`${block.writer_action ?? 'changed'} ${shortDateTime(block.writer_at)}`}
    >
      <span className="font-mono">{who}</span> · {ago(block.writer_at)}
    </span>
  )
}

function Blocks({ cell }: { cell: CellView }) {
  if (cell.blocks.length === 0) {
    return (
      <EmptyNote>
        {cell.delivery_id
          ? 'The delivery for this start has no stored blocks.'
          : 'This start has no Agent Hub delivery recorded.'}
      </EmptyNote>
    )
  }
  const max = Math.max(...cell.blocks.map((b) => b.tokens))
  return (
    <ul className="divide-y divide-slate-800/70">
      {cell.blocks.map((b) => (
        <li key={b.block_id} className="py-2">
          <div className="flex items-baseline justify-between gap-3">
            <span
              className="min-w-0 truncate text-sm text-slate-200"
              title={b.label}
            >
              {b.label}
            </span>
            <span className="font-mono text-sm text-slate-100">
              {tok(b.tokens)}
            </span>
          </div>
          <div className="mt-1 h-1 rounded-sm bg-slate-800/50">
            <div
              className="h-full rounded-sm bg-amber-400/70"
              style={{ width: `${(b.tokens / max) * 100}%` }}
            />
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
            <span>{b.scope ?? '—'}</span>
            <span>{b.kind ?? b.source_type}</span>
            <span className="font-mono" title={b.revision ?? undefined}>
              r {shortRevision(b.revision)}
            </span>
            <span>
              last writer: <Writer block={b} />
            </span>
          </div>
        </li>
      ))}
    </ul>
  )
}

function Growth({ cell }: { cell: CellView }) {
  const g = cell.growth
  if (g.measured === 0) {
    return <EmptyNote>No peak read for these sessions yet.</EmptyNote>
  }
  return (
    <dl className="grid grid-cols-2 gap-4 text-xs sm:grid-cols-4">
      {(
        [
          ['Median first turn', tok(g.median_first_turn)],
          ['Median peak', tok(g.median_peak)],
          ['Largest peak', tok(g.max_peak)],
          [
            'Compacted',
            `${g.compacted} of ${g.measured} · ${g.compactions} ${g.compactions === 1 ? 'time' : 'times'}`,
          ],
        ] as const
      ).map(([k, v]) => (
        <div key={k}>
          <dt className="text-slate-500">{k}</dt>
          <dd className="font-mono text-base text-slate-100">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="panel-surface p-4 lg:p-5">
      <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
        {title}
      </h2>
      {children}
    </section>
  )
}

function CellBody({ cell }: { cell: CellView }) {
  const latest = cell.latest
  const state = cell.state
  const move = cell.latest_move
  if (!latest) {
    return (
      <div className="panel-surface">
        <EmptyNote>
          No measured starts for {harnessLabel(cell.harness)} ·{' '}
          {roleLabel(cell.role)} in the last {cell.lookback_days} days.
        </EmptyNote>
      </div>
    )
  }
  const old = ageDays(latest.at) >= 3
  return (
    <>
      <section className="panel-surface space-y-3 p-4 lg:p-5">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className="font-mono text-3xl font-semibold text-slate-50">
            {tok(latest.total)}
          </span>
          <span className="text-xs text-slate-400">
            latest start {shortDateTime(latest.at)} ({ago(latest.at)})
            {old && <span className="ml-1 text-amber-300">stale</span>}
          </span>
        </div>
        <TokenBar
          total={latest.total}
          harness={latest.harness_tokens}
          ours={latest.ours}
          brief={latest.brief}
          scale={latest.total}
        />
        <PartsLegend />
        <p className="text-xs text-slate-500">
          {harnessLabel(cell.harness)} {latest.version ?? '—'} ·{' '}
          {latest.model ?? '—'} · config{' '}
          <span className="font-mono">
            {cell.config_fp?.slice(0, 8) ?? '—'}
          </span>
          {' · '}
          <span className="font-mono" title="Session of the latest start">
            {latest.session_id.slice(0, 8)}
          </span>
        </p>
        <p className="flex flex-wrap items-center gap-x-3 text-xs text-slate-400">
          {cell.budget_warn != null ? (
            <span>Warn level {tok(cell.budget_warn)}</span>
          ) : (
            <span>No warn level set</span>
          )}
          {state?.reason ? (
            <span className="inline-flex items-center gap-1 font-medium text-amber-300">
              <Flag className="h-3 w-3" aria-hidden="true" />
              {state.reason === 'warn' ? 'Over budget' : 'Jumped'}: last 24 h
              median {tok(state.recent)}
              {state.body_pct != null &&
                ` (${signedPct(state.body_pct)} on the week before, without the brief)`}
            </span>
          ) : state ? (
            <span>
              Last 24 h median {tok(state.recent)} ({state.n_recent}{' '}
              {state.n_recent === 1 ? 'start' : 'starts'}), under budget
            </span>
          ) : (
            <span>Budget state is kept per role cell, not for a group.</span>
          )}
        </p>
      </section>

      {move && (
        <Section title="Last move">
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <span
              className="inline-flex items-center gap-1.5 font-semibold"
              style={{
                color: (CAUSE_META[move.cause] ?? CAUSE_META.none).color,
              }}
            >
              <span
                className="h-2.5 w-2.5 rotate-45"
                style={{
                  background: (CAUSE_META[move.cause] ?? CAUSE_META.none).color,
                }}
              />
              {(CAUSE_META[move.cause] ?? CAUSE_META.none).label}
            </span>
            <span className="text-slate-400">{shortDateTime(move.at)}</span>
            <span className="font-mono text-slate-200">
              {signedTok(move.delta)}{' '}
              {move.pct != null && `(${signedPct(move.pct)})`}
            </span>
          </p>
          <p className="mt-1 text-sm text-slate-300">{move.summary}</p>
          <Link
            href={trendHref(cell.harness, cell.role)}
            prefetch={false}
            className="mt-2 inline-block text-xs text-amber-300 underline underline-offset-2 focus-ring-amber"
          >
            Open the trend
          </Link>
        </Section>
      )}

      <Section title="Where the first turn goes">
        <Parts cell={cell} />
      </Section>

      <Section
        title={`What we delivered${cell.blocks_total != null ? ` · ${tok(cell.blocks_total)} in ${cell.blocks.length} blocks` : ''}`}
      >
        <Blocks cell={cell} />
      </Section>

      <Section title={`Inside a session · last ${cell.lookback_days} days`}>
        <Growth cell={cell} />
      </Section>

      <Section title="Recent starts">
        <ul className="divide-y divide-slate-800/70">
          {cell.recent.map((r) => (
            <li
              key={r.session_id}
              className="flex flex-wrap items-baseline justify-between gap-x-3 py-1.5 text-xs"
            >
              <span className="font-mono text-sm text-slate-100">
                {tok(r.total)}
              </span>
              <span className="text-slate-400">{shortDateTime(r.at)}</span>
              <span className="text-slate-500">
                {r.version ?? '—'} · {r.model ?? '—'}
              </span>
            </li>
          ))}
        </ul>
      </Section>
    </>
  )
}

function CellScreen() {
  const params = useParams<{ harness: string; role: string }>()
  const harness = decodeURIComponent(params.harness)
  const role = decodeURIComponent(params.role)
  const query = useQuery({
    queryKey: ['context-cell', harness, role],
    queryFn: () => fetchCell(harness, role),
    refetchInterval: 60_000,
  })
  const data = query.data
  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />
      <ContextHeader />
      <main className="page-frame">
        <div className="page-container max-w-5xl space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <Link
                href="/context"
                prefetch={false}
                className="mb-1 inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200 focus-ring-amber"
              >
                <ArrowLeft className="h-3 w-3" />
                Cost
              </Link>
              <h2 className="text-lg font-semibold text-slate-50">
                {harnessLabel(harness)} · {roleLabel(role)}
              </h2>
            </div>
            <Link
              href={trendHref(harness, role)}
              prefetch={false}
              className={cn('button-secondary text-xs focus-ring-amber')}
            >
              Trend
            </Link>
          </div>
          {query.isError && (
            <FailedNotice
              what="this cell"
              error={query.error}
              hasData={Boolean(data)}
              updatedAt={query.dataUpdatedAt}
              onRetry={() => query.refetch()}
            />
          )}
          {!data && query.isLoading && (
            <div className="space-y-3" aria-busy="true" aria-label="Loading">
              <Skeleton className="h-36" />
              <Skeleton className="h-48" />
            </div>
          )}
          {data && <CellBody cell={data} />}
        </div>
      </main>
    </div>
  )
}

export default function ContextCellPage() {
  return (
    <Suspense>
      <CellScreen />
    </Suspense>
  )
}
