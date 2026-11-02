'use client'

import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import { useId, useState } from 'react'
import {
  fetchLookIntoModels,
  LOOKINTO_OPEN,
  type LookInto,
} from '@/lib/api/context-changes'
import { cn } from '@/lib/utils'

const TONE: Record<string, string> = {
  queued: 'text-sky-200',
  working: 'text-sky-200',
  'needs-you': 'text-amber-200',
  fixed: 'text-emerald-200',
  nothing: 'text-slate-300',
  failed: 'text-red-200',
  ended: 'text-slate-300',
  unknown: 'text-slate-400',
}

export const lookIntoOpen = (l: LookInto | null | undefined) =>
  !!l && LOOKINTO_OPEN.includes(l.state)

/** One line: what the agent this row was handed to is doing, with its Aico window. */
export function LookIntoStatus({
  lookinto,
  starting,
}: {
  lookinto: LookInto | null
  starting: boolean
}) {
  if (starting)
    return (
      <p role="status" className="mt-2 text-xs text-sky-200">
        Starting an agent…
      </p>
    )
  if (!lookinto) return null
  const text =
    lookinto.state === 'unknown'
      ? 'Agent status unknown (Nightshift did not answer)'
      : lookinto.text || lookinto.state
  return (
    <p
      role="status"
      data-testid="lookinto-status"
      className={cn(
        'mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs',
        TONE[lookinto.state] ?? 'text-slate-300',
      )}
    >
      <span className="min-w-0 break-words">{text}</span>
      {lookinto.link && (
        <a
          href={lookinto.link}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-amber-300/90 underline underline-offset-2 focus-ring-amber"
        >
          Open in Aico
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
      )}
    </p>
  )
}

/** The owner's words and an optional model, then one agent decides this row. */
export function LookIntoPanel({
  project,
  busy,
  onSubmit,
  onCancel,
}: {
  /** The row's look-in project: its launch table gives the model list. */
  project?: string | null
  busy: boolean
  onSubmit: (note: string, model: string | null) => void
  onCancel: () => void
}) {
  const id = useId()
  const [note, setNote] = useState('')
  const [model, setModel] = useState('')
  const models = useQuery({
    queryKey: ['context-changes-lookinto-models', project ?? null],
    queryFn: () => fetchLookIntoModels(project),
    staleTime: 10 * 60_000,
    retry: false,
  })
  const standard = models.data?.standard
  return (
    <div className="mt-2 space-y-3 rounded-lg border border-slate-700/70 bg-slate-950/60 p-3">
      <p className="text-xs text-slate-400">
        An agent reads this change and keeps, reworks or refuses it, this row
        only. Its decision shows under Kept, Reworked or Refused.
      </p>
      <div>
        <label
          htmlFor={`${id}-note`}
          className="text-[11px] font-semibold text-slate-300"
        >
          Note for the agent (optional)
        </label>
        <textarea
          id={`${id}-note`}
          rows={2}
          maxLength={2000}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="What you want checked, or which way you lean"
          className="control-input mt-1 text-xs"
        />
      </div>
      <div>
        <label
          htmlFor={`${id}-model`}
          className="text-[11px] font-semibold text-slate-300"
        >
          Model
        </label>
        <select
          id={`${id}-model`}
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="control-select mt-1 block h-8 py-0 text-xs"
        >
          <option value="">
            {standard
              ? `Table default (${standard.model})`
              : 'Table default for review'}
          </option>
          {(models.data?.options ?? [])
            .filter((o) => o.model !== standard?.model)
            .map((o) => (
              <option key={o.model} value={o.model}>
                {o.model} ({o.tool}
                {o.effort ? `, ${o.effort}` : ''})
              </option>
            ))}
        </select>
        {models.isError && (
          <p className="mt-1 text-[11px] text-slate-500">
            Couldn't load the model list; the table's default runs.
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => onSubmit(note, model || null)}
          className="h-9 rounded-lg bg-amber-500 px-4 text-xs font-semibold text-neutral-950 hover:bg-amber-400 focus-ring-amber disabled:opacity-40"
        >
          Start agent
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="h-9 rounded-lg border border-slate-700/80 px-3 text-xs text-slate-300 hover:bg-slate-800 focus-ring-amber"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
