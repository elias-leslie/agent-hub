'use client'

import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import {
  type DecideResponse,
  type DecisionKind,
  type Edit,
  itemOf,
  keepChanges,
  type LookInto,
  lookIntoChange,
  type Narrow,
  type Queue,
  type QueueRow,
  ReviewError,
  refuseChanges,
  reworkChange,
} from '@/lib/api/context-changes'
import type { Problem } from './components/ChangeRow'

const OUTCOME_TEXT: Record<string, string> = {
  archived: 'archived',
  restored: 'put back',
  disabled: 'turned off',
  edited: 'edited',
  narrowed: 'narrowed',
  recorded: 'kept',
  'nothing to undo': 'nothing to undo',
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

export function describe(
  verb: DecisionKind,
  rows: QueueRow[],
  res: DecideResponse,
): string {
  const done =
    verb === 'keep' ? 'Kept' : verb === 'refuse' ? 'Refused' : 'Reworked'
  const head =
    rows.length === 1
      ? `${done} “${rows[0].title}”`
      : `${done} ${plural(rows.length, 'change')}`
  const counts = new Map<string, number>()
  for (const r of res.results) {
    const text = OUTCOME_TEXT[r.outcome] ?? r.outcome
    counts.set(text, (counts.get(text) ?? 0) + 1)
  }
  const detail =
    verb === 'keep'
      ? ''
      : ` (${[...counts].map(([t, n]) => (rows.length === 1 ? t : `${n} ${t}`)).join(', ')})`
  const undid = res.results.reduce((n, r) => n + r.also_undid.length, 0)
  const extra = [
    undid ? `It also put back ${plural(undid, 'later edit')}.` : '',
    res.linked_pending.length
      ? `${plural(res.linked_pending.length, 'more change')} from the same session ${res.linked_pending.length === 1 ? 'is' : 'are'} still waiting.`
      : '',
  ].filter(Boolean)
  return [`${head}${detail}.`, ...extra].join(' ')
}

export const CONFLICT_RELOADED =
  'Changed since you loaded it. Reloaded; check the diff and decide again. Nothing was changed.'
export const CONFLICT_GONE =
  'Changed since you loaded it, and it is no longer waiting here. Nothing was changed. Check Kept, Reworked and Refused before acting again.'

/** Runs keep / refuse / rework against the API and keeps the per-row outcome state the page shows. */
export function useReview(
  rows: QueueRow[],
  reload: () => Promise<Queue | undefined>,
) {
  const client = useQueryClient()
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set())
  const [problems, setProblems] = useState<Record<string, Problem>>({})
  const [ghosts, setGhosts] = useState<
    Record<string, { row: QueueRow; index: number }>
  >({})
  const [notice, setNotice] = useState<string | null>(null)
  // Look-ins this page just started, shown until a reload carries Nightshift's own status.
  const [starting, setStarting] = useState<ReadonlySet<string>>(new Set())
  const [started, setStarted] = useState<Record<string, LookInto>>({})

  const setProblem = (key: string, problem: Problem | null) =>
    setProblems((p) => {
      const next = { ...p }
      if (problem) next[key] = problem
      else delete next[key]
      return next
    })

  const decide = useCallback(
    async (
      scope: string,
      targets: QueueRow[],
      verb: DecisionKind,
      call: () => Promise<DecideResponse>,
    ) => {
      const keys = targets.map((t) => t.key)
      const marked = [scope, ...keys]
      setBusy((b) => new Set([...b, ...marked]))
      setProblems((p) =>
        Object.fromEntries(
          Object.entries(p).filter(([k]) => !marked.includes(k)),
        ),
      )
      setNotice(null)
      try {
        const res = await call()
        setNotice(describe(verb, targets, res))
        setGhosts((g) =>
          Object.fromEntries(
            Object.entries(g).filter(([k]) => !keys.includes(k)),
          ),
        )
        await reload()
        client.invalidateQueries({ queryKey: ['context-decisions'] })
      } catch (error) {
        if (error instanceof ReviewError && error.kind === 'conflict') {
          const moved =
            error.key && keys.includes(error.key) ? [error.key] : keys
          const index = new Map(rows.map((r, i) => [r.key, i]))
          const fresh = await reload().catch(() => undefined)
          const live = new Set(fresh?.rows.map((r) => r.key))
          const at = Date.now()
          setGhosts((g) => {
            const next = { ...g }
            for (const t of targets)
              if (moved.includes(t.key) && fresh && !live.has(t.key))
                next[t.key] = { row: t, index: index.get(t.key) ?? 0 }
            return next
          })
          for (const key of moved) {
            const there = !fresh || live.has(key)
            setProblem(key, {
              kind: there ? 'conflict' : 'gone',
              message: there ? CONFLICT_RELOADED : CONFLICT_GONE,
              at,
            })
          }
          if (keys.length > 1) {
            setProblem(scope, {
              kind: 'conflict',
              message: `Changed since you loaded it, so nothing was changed. Reloaded; the row that moved is marked below.`,
              at,
            })
          }
        } else if (error instanceof ReviewError && error.kind === 'invalid') {
          setProblem(scope, {
            kind: 'invalid',
            message: `Not saved: ${error.message}`,
            at: Date.now(),
          })
        } else {
          const why = error instanceof Error ? error.message : 'unknown error'
          setProblem(scope, {
            kind: 'other',
            message: `Couldn't confirm the result (${why}). Reload before trying again; it may or may not have gone through.`,
            at: Date.now(),
          })
        }
      } finally {
        setBusy((b) => new Set([...b].filter((k) => !marked.includes(k))))
      }
    },
    [client, reload, rows],
  )

  const lookInto = useCallback(
    async (row: QueueRow, note: string, model: string | null) => {
      setStarting((s) => new Set([...s, row.key]))
      setProblem(row.key, null)
      try {
        const res = await lookIntoChange(row, note, model)
        setStarted((s) => ({ ...s, [row.key]: res.lookinto }))
        await reload().catch(() => undefined)
      } catch (error) {
        if (error instanceof ReviewError && error.kind === 'conflict') {
          const fresh = await reload().catch(() => undefined)
          const there = !fresh || fresh.rows.some((r) => r.key === row.key)
          setProblem(row.key, {
            kind: there ? 'conflict' : 'gone',
            message: error.message,
            at: Date.now(),
          })
        } else {
          const why = error instanceof Error ? error.message : 'unknown error'
          setProblem(row.key, {
            kind: 'other',
            message:
              error instanceof ReviewError && error.status === 502
                ? why
                : `Couldn't confirm whether an agent started (${why}). Reload to see.`,
            at: Date.now(),
          })
        }
      } finally {
        setStarting((s) => new Set([...s].filter((k) => k !== row.key)))
      }
    },
    [reload],
  )

  return {
    busy,
    starting,
    /** The row's look-in: Nightshift's status from the last load, else the one this page just started. */
    lookIntoOf: (row: QueueRow): LookInto | null =>
      row.lookinto && row.lookinto.state !== 'unknown'
        ? row.lookinto
        : (started[row.key] ?? row.lookinto ?? null),
    lookInto,
    problems,
    ghosts,
    notice,
    dismissNotice: () => setNotice(null),
    dismiss: (key: string) => {
      setProblem(key, null)
      setGhosts((g) =>
        Object.fromEntries(Object.entries(g).filter(([k]) => k !== key)),
      )
    },
    keep: (scope: string, targets: QueueRow[]) =>
      decide(scope, targets, 'keep', () => keepChanges(targets.map(itemOf))),
    refuse: (scope: string, targets: QueueRow[]) =>
      decide(scope, targets, 'refuse', () =>
        refuseChanges(targets.map(itemOf)),
      ),
    rework: (row: QueueRow, change: { narrow: Narrow } | { edit: Edit }) =>
      decide(row.key, [row], 'rework', () => reworkChange(itemOf(row), change)),
  }
}
