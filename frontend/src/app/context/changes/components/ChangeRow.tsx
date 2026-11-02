'use client'

import { AlertTriangle, Bot, Check, Pencil, Undo2, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type {
  Edit,
  LookInto,
  Narrow,
  QueueRow,
} from '@/lib/api/context-changes'
import { cn } from '@/lib/utils'
import { ago, shortDateTime } from '../../format'
import { rowDiff } from '../diff'
import {
  alsoUndoesText,
  CHANGE_LABEL,
  KIND_LABEL,
  laterWriteText,
  perDay,
  perStart,
  preview,
  reachLabel,
  receiversShort,
  sessionShort,
  writersLabel,
} from '../present'
import { DiffView } from './DiffView'
import { LookIntoPanel, LookIntoStatus, lookIntoOpen } from './LookInto'
import { ReworkPanel } from './ReworkPanel'

/** Why the last decision on a row did not go through. `gone`: the row is no longer waiting. */
export interface Problem {
  kind: 'conflict' | 'invalid' | 'other' | 'gone'
  message: string
  at: number
}

export interface RowActions {
  keep: (row: QueueRow) => void
  refuse: (row: QueueRow) => void
  rework: (row: QueueRow, change: { narrow: Narrow } | { edit: Edit }) => void
  lookInto: (row: QueueRow, note: string, model: string | null) => void
  dismiss: (key: string) => void
  filterSession: (session: string) => void
}

function Cell({
  label,
  children,
  title,
}: {
  label: string
  children: React.ReactNode
  title?: string
}) {
  return (
    <div className="min-w-0" title={title}>
      <dt className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
        {label}
      </dt>
      <dd className="mt-0.5 break-words text-xs text-slate-200">{children}</dd>
    </div>
  )
}

const PROBLEM_TONE: Record<Problem['kind'], string> = {
  conflict: 'border-amber-500/40 bg-amber-500/10 text-amber-100',
  gone: 'border-slate-600/60 bg-slate-800/60 text-slate-200',
  invalid: 'border-red-500/30 bg-red-500/10 text-red-200',
  other: 'border-red-500/30 bg-red-500/10 text-red-200',
}

function ProblemNote({
  problem,
  onDismiss,
}: {
  problem: Problem
  onDismiss: () => void
}) {
  return (
    <div
      role={
        problem.kind === 'conflict' || problem.kind === 'gone'
          ? 'status'
          : 'alert'
      }
      className={cn(
        'mt-2 flex items-start gap-2 rounded-lg border px-3 py-2 text-xs',
        PROBLEM_TONE[problem.kind],
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
  )
}

export function ChangeRow({
  row,
  busy,
  problem,
  gone,
  grouped,
  lookinto = null,
  starting = false,
  actions,
}: {
  row: QueueRow
  busy: boolean
  /** The row's hand-off to an agent, if any (see useReview.lookIntoOf). */
  lookinto?: LookInto | null
  /** A Look into it request is on its way. */
  starting?: boolean
  problem?: Problem
  /** Kept in view after a conflict although the server no longer lists it as waiting. */
  gone?: boolean
  /** Shown inside its session's card, which already says the session wrote several. */
  grouped?: boolean
  actions: RowActions
}) {
  const [reworking, setReworking] = useState(false)
  const [asking, setAsking] = useState(false)
  const [diffOpen, setDiffOpen] = useState(false)
  const ref = useRef<HTMLLIElement>(null)
  const diff = useMemo(() => rowDiff(row), [row])
  const reach = reachLabel(row)
  const hint = row.hint
  const disabled = busy || gone
  const agentOpen = lookIntoOpen(lookinto)
  const conflictAt =
    problem?.kind === 'conflict' || problem?.kind === 'gone' ? problem.at : null

  // A conflict reloads the list; keep the row the owner was deciding on in view.
  useEffect(() => {
    if (conflictAt != null)
      ref.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
  }, [conflictAt])

  const summaryBits = [
    diff.added || diff.removed ? `+${diff.added} −${diff.removed} lines` : null,
    ...diff.fields
      .slice(0, 3)
      .map((f) => `${f.label}: ${f.before} → ${f.after}`),
    diff.fields.length > 3 ? `${diff.fields.length - 3} more fields` : null,
  ].filter(Boolean)
  const body = typeof row.after?.content === 'string' ? row.after.content : ''
  const what =
    row.change === 'create' && body
      ? preview(body)
      : row.change === 'delete'
        ? 'Deleted. Refuse puts it back.'
        : summaryBits.join(' · ') || 'No visible change in the text.'

  return (
    <li
      ref={ref}
      data-row-key={row.key}
      className={cn(
        'rounded-xl border bg-slate-900/60 p-3',
        conflictAt != null ? 'border-amber-500/50' : 'border-slate-800/80',
        gone && 'opacity-80',
      )}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="rounded-md bg-slate-800 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-300">
          {KIND_LABEL[row.target_kind]}
        </span>
        <span className="rounded-md bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-200">
          {CHANGE_LABEL[row.change]}
          {row.actions.length > 1 ? ` ×${row.actions.length}` : ''}
        </span>
        <h3 className="order-last min-w-0 basis-full break-words text-sm font-medium text-slate-100 sm:order-none sm:basis-0 sm:flex-1">
          {row.title}
        </h3>
        <span
          className="ml-auto shrink-0 text-[11px] text-slate-500 sm:order-last sm:ml-0"
          title={`First change ${shortDateTime(row.first_at)}, latest ${shortDateTime(row.last_at)}`}
        >
          {ago(row.last_at)}
        </span>
      </div>

      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        <Cell label="Scope">
          {row.scope_before && row.scope_before !== row.scope_after ? (
            <>
              <span className="text-slate-400">{row.scope_before}</span>
              <span aria-hidden="true" className="px-1 text-slate-600">
                →
              </span>
              <span className="sr-only"> to </span>
              {row.scope_after}
            </>
          ) : (
            row.scope_after
          )}
        </Cell>
        <Cell
          label="Per start"
          title="Tokens this change adds to every start that receives it"
        >
          <span className="font-mono">{perStart(row)}</span>
        </Cell>
        <Cell label="Reach" title={reach.detail}>
          <span className={cn(!row.reach && 'text-slate-400')}>
            {row.reach ? (
              reach.short
            ) : (
              <>
                — <span className="text-slate-500">(not known yet)</span>
              </>
            )}
          </span>
          {row.reach && (
            <>
              {row.tokens_per_day != null && (
                <span className="font-mono text-slate-400">
                  {' '}
                  · {perDay(row)}
                </span>
              )}
              {receiversShort(row) && (
                <span className="block truncate text-[11px] text-slate-500">
                  {receiversShort(row)}
                </span>
              )}
            </>
          )}
        </Cell>
        <Cell label="Written by">
          {row.writers.length === 0 ? (
            <span className="text-slate-400">unknown</span>
          ) : (
            <span>{writersLabel(row)}</span>
          )}
          {row.sessions[0] && (
            <button
              type="button"
              onClick={() => actions.filterSession(row.sessions[0])}
              title="Show only this session's changes"
              className="block text-[11px] text-amber-300/90 underline underline-offset-2 focus-ring-amber"
            >
              only {sessionShort(row.sessions[0])}
            </button>
          )}
        </Cell>
      </dl>

      {hint && (
        <p
          className={cn(
            'mt-2 text-xs',
            hint.decision === 'keep' ? 'text-slate-500' : 'text-amber-200/90',
          )}
          title={hint.reason ?? undefined}
        >
          Review agent: {hint.label}
          {hint.confidence != null
            ? ` (${Math.round(hint.confidence * 100)}%)`
            : ''}
          <span className="text-slate-500"> · a hint, your call</span>
        </p>
      )}

      <details
        className="mt-2"
        open={diffOpen}
        onToggle={(e) =>
          setDiffOpen((e.currentTarget as HTMLDetailsElement).open)
        }
      >
        <summary className="cursor-pointer break-words text-xs text-slate-300 focus-ring-amber">
          <span className="text-slate-500">What changed: </span>
          {what}
        </summary>
        {diffOpen && <DiffView diff={diff} label={row.title} />}
      </details>

      {problem && (
        <ProblemNote
          problem={problem}
          onDismiss={() => actions.dismiss(row.key)}
        />
      )}

      {!grouped && row.linked.length > 0 && (
        <p className="mt-2 text-[11px] text-slate-500">
          The same session also changed {row.linked.length} other item
          {row.linked.length > 1 ? 's' : ''} waiting here.
        </p>
      )}

      {!gone && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={disabled}
            onClick={() => actions.keep(row)}
            title="Leave it as it is and stop listing it"
            aria-label={`Keep ${row.title}`}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/20 focus-ring-amber disabled:opacity-40"
          >
            <Check className="h-3.5 w-3.5" aria-hidden="true" />
            Keep
          </button>
          {row.target_kind !== 'placement' && row.after != null && (
            <button
              type="button"
              disabled={disabled}
              aria-expanded={reworking}
              onClick={() => setReworking((v) => !v)}
              title="Narrow it to a project, role or this session, or edit the text"
              aria-label={`Rework ${row.title}`}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-slate-600/70 bg-slate-800/60 px-3 text-xs font-semibold text-slate-200 hover:bg-slate-800 focus-ring-amber disabled:opacity-40"
            >
              <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
              Rework
            </button>
          )}
          <button
            type="button"
            disabled={disabled}
            onClick={() => actions.refuse(row)}
            title={
              row.change === 'create'
                ? 'Undo it: the new item is archived'
                : 'Undo it: the version from before is put back'
            }
            aria-label={`Refuse ${row.title}`}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-red-500/40 bg-red-500/10 px-3 text-xs font-semibold text-red-200 hover:bg-red-500/20 focus-ring-amber disabled:opacity-40"
          >
            <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
            Refuse
          </button>
          <button
            type="button"
            disabled={disabled || starting || agentOpen}
            aria-expanded={asking}
            onClick={() => setAsking((v) => !v)}
            title={
              agentOpen
                ? 'An agent is already on this one'
                : 'Hand this change to an agent that keeps, reworks or refuses it'
            }
            aria-label={`Look into ${row.title}`}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 text-xs font-semibold text-sky-200 hover:bg-sky-500/20 focus-ring-amber disabled:opacity-40"
          >
            <Bot className="h-3.5 w-3.5" aria-hidden="true" />
            Look into it
          </button>
          {busy && <span className="text-xs text-slate-400">Saving…</span>}
        </div>
      )}

      {!gone && <LookIntoStatus lookinto={lookinto} starting={starting} />}

      {asking && !gone && !agentOpen && !starting && (
        <LookIntoPanel
          busy={!!disabled}
          onCancel={() => setAsking(false)}
          onSubmit={(note, model) => {
            setAsking(false)
            actions.lookInto(row, note, model)
          }}
        />
      )}

      {!gone && row.also_undoes.length > 0 && (
        <p
          className="mt-2 flex items-start gap-1.5 text-xs text-amber-200"
          data-testid="also-undoes"
        >
          <AlertTriangle
            className="mt-0.5 h-3.5 w-3.5 shrink-0"
            aria-hidden="true"
          />
          <span>
            Refusing also puts back {alsoUndoesText(row.also_undoes)}:{' '}
            {row.also_undoes.map(laterWriteText).join(', ')}.
          </span>
        </p>
      )}

      {reworking && !gone && (
        <ReworkPanel
          row={row}
          busy={busy}
          onCancel={() => setReworking(false)}
          onSubmit={(change) => actions.rework(row, change)}
        />
      )}
    </li>
  )
}
