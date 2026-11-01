'use client'

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { RefreshCw, X } from 'lucide-react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useCallback, useMemo } from 'react'
import {
  DECISION_LIMIT,
  type DecisionKind,
  fetchChanges,
  fetchDecisions,
  type Queue,
  type QueueRow,
} from '@/lib/api/context-changes'
import { cn } from '@/lib/utils'
import { ContextHeader } from '../components/ContextHeader'
import { EmptyNote, FailedNotice, Skeleton } from '../components/Notices'
import { ago, shortDateTime, signedTok } from '../format'
import { ChangeRow, type RowActions } from './components/ChangeRow'
import { DecidedList } from './components/DecidedList'
import {
  alsoUndoesText,
  type Group,
  groupRows,
  KIND_LABEL,
  scopeWord,
  sessionShort,
  writersLabel,
} from './present'
import { useReview } from './useReview'

type Tab = 'unreviewed' | DecisionKind
const TABS: { id: Tab; label: string }[] = [
  { id: 'unreviewed', label: 'Unreviewed' },
  { id: 'keep', label: 'Kept' },
  { id: 'rework', label: 'Reworked' },
  { id: 'refuse', label: 'Refused' },
]
const STALE_AFTER_MS = 5 * 60_000

interface Filters {
  tab: Tab
  session: string | null
  kind: string | null
  scope: string | null
}

function useFilters() {
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const key = params.toString()
  const filters = useMemo<Filters>(() => {
    const p = new URLSearchParams(key)
    const tab = p.get('tab') as Tab
    return {
      tab: TABS.some((t) => t.id === tab) ? tab : 'unreviewed',
      session: p.get('session'),
      kind: p.get('kind'),
      scope: p.get('scope'),
    }
  }, [key])
  const update = useCallback(
    (patch: Partial<Filters>) => {
      const next = { ...filters, ...patch }
      const p = new URLSearchParams()
      if (next.tab !== 'unreviewed') p.set('tab', next.tab)
      for (const k of ['session', 'kind', 'scope'] as const)
        if (next[k]) p.set(k, next[k] as string)
      const qs = p.toString()
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
    },
    [filters, pathname, router],
  )
  return { filters, update }
}

function Notice({ text, onDismiss }: { text: string; onDismiss: () => void }) {
  return (
    <div
      role="status"
      className="flex items-start gap-2 rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-4 py-2 text-sm text-emerald-100"
    >
      <span className="min-w-0 flex-1">{text}</span>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="rounded p-0.5 hover:bg-white/10 focus-ring-amber"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}

function GroupCard({
  group,
  busy,
  problem,
  onKeepAll,
  onRefuseAll,
  onDismiss,
  children,
}: {
  group: Group
  busy: boolean
  problem?: { message: string; kind: string }
  onKeepAll: () => void
  onRefuseAll: () => void
  onDismiss: () => void
  children: React.ReactNode
}) {
  const undoes = group.rows.flatMap((r) => r.also_undoes)
  const perDay = group.rows.some((r) => r.tokens_per_day != null)
    ? group.rows.reduce((n, r) => n + (r.tokens_per_day ?? 0), 0)
    : null
  const unknown = group.rows.filter((r) => r.tokens_per_day == null).length
  return (
    <section
      aria-label={`Changes from session ${sessionShort(group.session ?? '')}`}
      className="panel-surface p-3"
    >
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
          <h2 className="break-words text-sm font-semibold text-slate-100">
            {group.rows.length} changes from one session
          </h2>
          <p className="break-words text-xs text-slate-400">
            {writersLabel(group.rows[0])}
            {perDay != null && (
              <span className="font-mono">
                {' '}
                · {signedTok(perDay)} tok/day
                {unknown ? ` (+${unknown} unknown)` : ''}
              </span>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={onKeepAll}
            className="h-9 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/20 focus-ring-amber disabled:opacity-40"
          >
            Keep all ({group.rows.length})
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onRefuseAll}
            className="h-9 rounded-lg border border-red-500/40 bg-red-500/10 px-3 text-xs font-semibold text-red-200 hover:bg-red-500/20 focus-ring-amber disabled:opacity-40"
          >
            Refuse all ({group.rows.length})
          </button>
        </div>
      </header>
      {undoes.length > 0 && (
        <p className="mt-2 text-xs text-amber-200">
          Refusing all also puts back {alsoUndoesText(undoes)}.
        </p>
      )}
      {problem && (
        <div
          role={problem.kind === 'conflict' ? 'status' : 'alert'}
          className={cn(
            'mt-2 flex items-start gap-2 rounded-lg border px-3 py-2 text-xs',
            problem.kind === 'conflict'
              ? 'border-amber-500/40 bg-amber-500/10 text-amber-100'
              : 'border-red-500/30 bg-red-500/10 text-red-200',
          )}
        >
          <span className="min-w-0 flex-1">{problem.message}</span>
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss this note"
            className="rounded p-0.5 hover:bg-white/10 focus-ring-amber"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
      <ul className="mt-3 space-y-2">{children}</ul>
    </section>
  )
}

function AutomaticList({ queue }: { queue: Queue }) {
  const list = queue.automatic
  return (
    <details className="panel-surface p-3">
      <summary className="cursor-pointer text-xs font-semibold text-slate-300 focus-ring-amber">
        Automatic changes by the system, last 7 days ({list.length})
        <span className="font-normal text-slate-500">
          {' '}
          · never counted as waiting
        </span>
      </summary>
      {list.length === 0 ? (
        <p className="mt-2 text-xs text-slate-500">
          No automatic changes in the last 7 days.
        </p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {list.map((c) => (
            <li
              key={`${c.key}:${c.revision}`}
              className="text-xs text-slate-300"
            >
              <span className="mr-1.5 rounded bg-slate-800 px-1 py-0.5 text-[10px] uppercase text-slate-400">
                {KIND_LABEL[c.target_kind]}
              </span>
              <span className="break-words">{c.title}</span>
              <span className="text-slate-500">
                {' '}
                · {c.action} ·{' '}
                <span title={shortDateTime(c.at)}>{ago(c.at)}</span>
                {c.reason ? ` · ${c.reason}` : ''}
              </span>
            </li>
          ))}
        </ul>
      )}
    </details>
  )
}

function Unreviewed({
  filters,
  update,
}: {
  filters: Filters
  update: (p: Partial<Filters>) => void
}) {
  const query = useQuery({
    queryKey: ['context-changes'],
    queryFn: fetchChanges,
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
    retry: 1,
  })
  const queue = query.data
  const reload = useCallback(
    async () => (await query.refetch()).data,
    [query.refetch],
  )
  const rows = queue?.rows ?? []
  const review = useReview(rows, reload)

  // Rows that failed with a conflict and are no longer listed stay where they were.
  const merged = useMemo(() => {
    const list = [...rows]
    const missing = Object.entries(review.ghosts)
      .filter(([k]) => !rows.some((r) => r.key === k))
      .sort((a, b) => a[1].index - b[1].index)
    for (const [, g] of missing)
      list.splice(Math.min(g.index, list.length), 0, g.row)
    return list
  }, [rows, review.ghosts])

  const shown = merged.filter(
    (r) =>
      (!filters.session || r.sessions.includes(filters.session)) &&
      (!filters.kind || r.target_kind === filters.kind) &&
      (!filters.scope || scopeWord(r) === filters.scope),
  )
  const scopes = [...new Set(merged.map(scopeWord))].sort()
  const { groups, singles } = groupRows(shown)

  const actions: RowActions = {
    keep: (row) => review.keep(row.key, [row]),
    refuse: (row) => review.refuse(row.key, [row]),
    rework: (row, change) => review.rework(row, change),
    dismiss: review.dismiss,
    filterSession: (session) => update({ session }),
  }
  const renderRow = (row: QueueRow, grouped = false) => (
    <ChangeRow
      key={row.key}
      row={row}
      busy={review.busy.has(row.key)}
      problem={review.problems[row.key]}
      gone={!rows.some((r) => r.key === row.key)}
      grouped={grouped}
      actions={actions}
    />
  )

  const summary = queue?.summary
  const loadedAt = query.dataUpdatedAt
  const stale =
    !!queue && Date.now() - loadedAt > STALE_AFTER_MS && !query.isFetching

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Type"
          className="control-select h-8 py-0 text-xs"
          value={filters.kind ?? ''}
          onChange={(e) => update({ kind: e.target.value || null })}
        >
          <option value="">All types</option>
          {(['memory', 'prompt', 'placement'] as const).map((k) => (
            <option key={k} value={k}>
              {KIND_LABEL[k]}
            </option>
          ))}
        </select>
        <select
          aria-label="Scope"
          className="control-select h-8 py-0 text-xs"
          value={filters.scope ?? ''}
          onChange={(e) => update({ scope: e.target.value || null })}
        >
          <option value="">All scopes</option>
          {scopes.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {filters.session && (
          <button
            type="button"
            onClick={() => update({ session: null })}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 text-xs text-amber-100 focus-ring-amber"
          >
            Session {sessionShort(filters.session)}
            <X className="h-3 w-3" aria-hidden="true" />
            <span className="sr-only">Clear session filter</span>
          </button>
        )}
        <button
          type="button"
          onClick={() => query.refetch()}
          aria-label="Reload"
          disabled={query.isFetching}
          className="ml-auto rounded-lg border border-slate-700/80 p-1.5 text-slate-300 hover:bg-slate-800 focus-ring-amber disabled:opacity-50"
        >
          <RefreshCw
            className={cn('h-3.5 w-3.5', query.isFetching && 'animate-spin')}
          />
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        {summary && (
          <span>
            {summary.tokens_per_day !== 0 ||
            summary.unknown_reach < summary.count ? (
              <>
                <span className="font-mono text-slate-300">
                  {signedTok(summary.tokens_per_day)}
                </span>{' '}
                tok/day
                {summary.unknown_reach > 0 &&
                  ` (${summary.unknown_reach} with reach not known yet)`}
              </>
            ) : summary.count > 0 ? (
              'reach not known yet'
            ) : null}
          </span>
        )}
        {queue && (
          <span
            className={cn(stale && 'text-amber-300')}
            title={shortDateTime(new Date(loadedAt).toISOString())}
          >
            {stale ? 'Stale: loaded ' : 'Loaded '}
            {ago(new Date(loadedAt).toISOString())}
          </span>
        )}
      </div>

      {review.notice && (
        <Notice text={review.notice} onDismiss={review.dismissNotice} />
      )}
      {query.isError && (
        <FailedNotice
          what="the changes"
          error={query.error}
          hasData={!!queue}
          updatedAt={loadedAt || undefined}
          onRetry={() => query.refetch()}
        />
      )}

      {!queue && query.isPending && (
        <div
          className="space-y-2"
          aria-busy="true"
          aria-label="Loading changes"
        >
          <p className="text-xs text-slate-500">Loading changes…</p>
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      )}

      {queue && shown.length === 0 && (
        <div className="panel-surface">
          <EmptyNote>
            {rows.length === 0
              ? 'Nothing waiting for review. Changes agents make to memories, prompts and placement rules show up here after they write them.'
              : 'No waiting changes match these filters.'}
          </EmptyNote>
        </div>
      )}

      {groups.map((g) => (
        <GroupCard
          key={g.id}
          group={g}
          busy={review.busy.has(g.id)}
          problem={review.problems[g.id]}
          onKeepAll={() => review.keep(g.id, g.rows)}
          onRefuseAll={() => review.refuse(g.id, g.rows)}
          onDismiss={() => review.dismiss(g.id)}
        >
          {g.rows.map((r) => renderRow(r, true))}
        </GroupCard>
      ))}
      {singles.length > 0 && (
        <section aria-label="Single changes" className="space-y-2">
          {groups.length > 0 && (
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              Single changes
            </h2>
          )}
          <ul className="space-y-2">{singles.map((r) => renderRow(r))}</ul>
        </section>
      )}

      {queue && <AutomaticList queue={queue} />}
    </div>
  )
}

function Decided({ decision }: { decision: DecisionKind }) {
  const query = useQuery({
    queryKey: ['context-decisions'],
    queryFn: fetchDecisions,
    placeholderData: keepPreviousData,
    retry: 1,
  })
  const records = (query.data ?? []).filter((r) => r.decision === decision)
  return (
    <div className="space-y-3">
      {query.isError && (
        <FailedNotice
          what="past decisions"
          error={query.error}
          hasData={!!query.data}
          updatedAt={query.dataUpdatedAt || undefined}
          onRetry={() => query.refetch()}
        />
      )}
      {query.isPending && (
        <div
          className="space-y-2"
          aria-busy="true"
          aria-label="Loading decisions"
        >
          <p className="text-xs text-slate-500">Loading past decisions…</p>
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      )}
      {query.data && <DecidedList decision={decision} records={records} />}
      {query.data && query.data.length >= DECISION_LIMIT && (
        <p className="text-xs text-slate-500">
          Showing the latest {DECISION_LIMIT} decisions.
        </p>
      )}
    </div>
  )
}

function ChangesView() {
  const { filters, update } = useFilters()
  // Tab counts: waiting comes from the queue, decided from the decision list (both share the page's cache).
  const queue = useQuery({
    queryKey: ['context-changes'],
    queryFn: fetchChanges,
  })
  const decisions = useQuery({
    queryKey: ['context-decisions'],
    queryFn: fetchDecisions,
  })
  const count = (tab: Tab) =>
    tab === 'unreviewed'
      ? queue.data?.summary.count
      : decisions.data?.filter((r) => r.decision === tab).length

  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />
      <ContextHeader />
      <main className="page-container px-4 py-4 lg:px-8">
        <div className="mx-auto max-w-5xl space-y-3">
          <div
            role="group"
            aria-label="Review state"
            className="flex flex-wrap gap-1"
          >
            {TABS.map((t) => {
              const n = count(t.id)
              const active = filters.tab === t.id
              return (
                <button
                  key={t.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => update({ tab: t.id, session: null })}
                  className={cn(
                    'h-9 rounded-xl px-2.5 text-xs font-semibold transition-colors focus-ring-amber sm:px-3.5',
                    active
                      ? 'bg-amber-500 text-slate-950'
                      : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100',
                  )}
                >
                  {t.label}
                  {n != null && (
                    <span
                      className={cn(
                        'ml-1.5 font-mono',
                        active ? 'text-slate-900' : 'text-slate-500',
                      )}
                    >
                      {n}
                    </span>
                  )}
                </button>
              )
            })}
          </div>
          {filters.tab === 'unreviewed' ? (
            <Unreviewed filters={filters} update={update} />
          ) : (
            <Decided decision={filters.tab} />
          )}
        </div>
      </main>
    </div>
  )
}

export default function ContextChangesPage() {
  return (
    <Suspense>
      <ChangesView />
    </Suspense>
  )
}
