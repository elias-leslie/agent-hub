'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useMemo } from 'react'
import {
  type DecisionKind,
  fetchMemoryTitles,
  type ReviewRecord,
} from '@/lib/api/context-changes'
import { cn } from '@/lib/utils'
import { EmptyNote } from '../../components/Notices'
import { ago, shortDateTime } from '../../format'
import { KIND_LABEL } from '../present'

const TONE: Record<DecisionKind, string> = {
  keep: 'bg-emerald-500/15 text-emerald-200',
  rework: 'bg-sky-500/15 text-sky-200',
  refuse: 'bg-red-500/15 text-red-200',
}
const VERB: Record<DecisionKind, string> = {
  keep: 'Kept',
  rework: 'Reworked',
  refuse: 'Refused',
}
const EMPTY: Record<DecisionKind, string> = {
  keep: 'Nothing kept yet. Keep marks a change as reviewed and fine; it is then listed here.',
  rework:
    'Nothing reworked yet. Rework edits a change in place or narrows who gets it; it is then listed here.',
  refuse:
    'Nothing refused yet. Refuse undoes a change: a new memory or prompt is archived, an edit is put back; it is then listed here.',
}

/** The note as the owner reads it: a look-into agent's "look-into <id>: " start is shown as the decider instead. */
const noteText = (r: ReviewRecord) =>
  r.by_lookinto
    ? (r.note ?? '').replace(/^look-into [0-9a-f]*:\s*/, '')
    : r.note

function placementTitle(id: string) {
  const [profile, project] = id.split('|')
  return `${profile} placements${project ? ` in ${project}` : ''}`
}

export function DecidedList({
  decision,
  records,
}: {
  decision: DecisionKind
  records: ReviewRecord[]
}) {
  const memoryIds = useMemo(
    () => [
      ...new Set(
        records
          .filter((r) => r.target_kind === 'memory')
          .map((r) => r.target_id),
      ),
    ],
    [records],
  )
  // Decisions carry only the target id; titles are a nicety, so a failed lookup just leaves the short id.
  const titles = useQuery({
    queryKey: ['context-changes-titles', memoryIds],
    queryFn: () => fetchMemoryTitles(memoryIds),
    enabled: memoryIds.length > 0,
    staleTime: 5 * 60_000,
    retry: false,
  })
  if (records.length === 0) return <EmptyNote>{EMPTY[decision]}</EmptyNote>
  return (
    <ul className="space-y-2">
      {records.map((r) => {
        const title =
          r.target_kind === 'prompt'
            ? r.target_id
            : r.target_kind === 'placement'
              ? placementTitle(r.target_id)
              : (titles.data?.[r.target_id] ??
                `Memory ${r.target_id.slice(0, 8)}`)
        return (
          <li
            key={r.id}
            className="rounded-xl border border-slate-800/80 bg-slate-900/60 p-3"
          >
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span
                className={cn(
                  'rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
                  TONE[r.decision],
                )}
              >
                {VERB[r.decision]}
              </span>
              <span className="rounded-md bg-slate-800 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-300">
                {KIND_LABEL[r.target_kind]}
              </span>
              {r.target_kind === 'prompt' ? (
                <Link
                  href={`/prompts/${encodeURIComponent(r.target_id)}`}
                  prefetch={false}
                  className="min-w-0 flex-1 break-words text-sm font-medium text-slate-100 underline-offset-2 hover:underline focus-ring-amber"
                >
                  {title}
                </Link>
              ) : (
                <span className="min-w-0 flex-1 break-words text-sm font-medium text-slate-100">
                  {title}
                </span>
              )}
              <span
                className="shrink-0 text-[11px] text-slate-500"
                title={shortDateTime(r.created_at)}
              >
                {ago(r.created_at)}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-400">
              by{' '}
              {r.by_lookinto
                ? 'look-into agent'
                : r.by_kind === 'owner'
                  ? 'you'
                  : (r.by ?? '—')}
              {r.lookinto?.link && (
                <>
                  {' · '}
                  <a
                    href={r.lookinto.link}
                    target="_blank"
                    rel="noreferrer"
                    className="text-amber-300/90 underline underline-offset-2 focus-ring-amber"
                  >
                    Open in Aico
                  </a>
                </>
              )}
              {noteText(r) ? (
                <span className="text-slate-300"> · “{noteText(r)}”</span>
              ) : null}
            </p>
          </li>
        )
      })}
    </ul>
  )
}
