import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useEffect, useState } from 'react'
import {
  fetchSessionCloseSettings,
  type SessionCloseSettings,
  updateSessionCloseSettings,
} from '@/lib/api/sessions'
import { cn } from '@/lib/utils'

const QUERY_KEY = ['sessions', 'close-settings'] as const

type NumberKey = Exclude<
  keyof SessionCloseSettings,
  'codex_close_inactive_enabled' | 'updated_by'
>

interface NumberField {
  key: NumberKey
  label: string
  help: string
  unit: 'min' | 'h'
  min: number
  max: number
}

const FIELDS: NumberField[] = [
  {
    key: 'dead_candidate_after_minutes',
    label: 'Looks dead after',
    help: 'Quiet this long and the session is marked as possibly dead.',
    unit: 'min',
    min: 5,
    max: 1440,
  },
  {
    key: 'reapable_after_minutes',
    label: 'Close quiet sessions after',
    help: 'Closed when it also shows a dead sign and no lane holds it.',
    unit: 'min',
    min: 15,
    max: 10080,
  },
  {
    key: 'zero_event_close_after_minutes',
    label: 'Close empty sessions after',
    help: 'Sessions that never recorded anything.',
    unit: 'min',
    min: 15,
    max: 10080,
  },
  {
    key: 'transcript_sync_close_after_minutes',
    label: 'Close dead Codex transcripts after',
    help: 'Codex sessions seen only through their transcript.',
    unit: 'min',
    min: 15,
    max: 10080,
  },
  {
    key: 'completion_close_after_minutes',
    label: 'Close completions after',
    help: 'Single API completions left open.',
    unit: 'min',
    min: 15,
    max: 10080,
  },
  {
    key: 'any_session_close_after_minutes',
    label: 'Close any session after',
    help: 'Last resort for anything still open.',
    unit: 'min',
    min: 60,
    max: 40320,
  },
  {
    key: 'codex_scan_hours',
    label: 'Codex scan window',
    help: 'How far back the transcript sync looks.',
    unit: 'h',
    min: 1,
    max: 336,
  },
]

const input =
  'h-8 w-24 rounded-md border border-slate-800 bg-slate-950/60 px-2 text-right font-mono text-[12px] tabular-nums text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50'

function readable(minutes: number): string {
  if (minutes >= 1440 && minutes % 1440 === 0) return `${minutes / 1440} d`
  if (minutes >= 60 && minutes % 60 === 0) return `${minutes / 60} h`
  return ''
}

export function CloseSettingsPanel({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const settings = useQuery({
    queryKey: QUERY_KEY,
    queryFn: fetchSessionCloseSettings,
  })
  const [draft, setDraft] = useState<SessionCloseSettings | null>(null)
  const save = useMutation({
    mutationFn: (changes: Partial<SessionCloseSettings>) =>
      updateSessionCloseSettings(changes),
    onSuccess: (saved) => {
      queryClient.setQueryData(QUERY_KEY, saved)
      setDraft(saved)
    },
  })

  useEffect(() => {
    if (settings.data && draft === null) setDraft(settings.data)
  }, [settings.data, draft])

  const changed =
    draft !== null &&
    settings.data !== undefined &&
    (Object.keys(draft) as (keyof SessionCloseSettings)[]).some(
      (key) => key !== 'updated_by' && draft[key] !== settings.data[key],
    )

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!draft || !settings.data) return
    const changes: Partial<SessionCloseSettings> = {}
    for (const field of FIELDS) {
      if (draft[field.key] !== settings.data[field.key])
        changes[field.key] = draft[field.key]
    }
    if (
      draft.codex_close_inactive_enabled !==
      settings.data.codex_close_inactive_enabled
    )
      changes.codex_close_inactive_enabled = draft.codex_close_inactive_enabled
    save.mutate(changes)
  }

  return (
    <section
      id="session-close-settings"
      aria-labelledby="session-close-settings-title"
      className="mt-2 rounded-lg border border-slate-800 bg-slate-950/80 p-3"
    >
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h2
          id="session-close-settings-title"
          className="text-[13px] font-semibold text-slate-100"
        >
          When sessions close
        </h2>
        <button
          type="button"
          onClick={onClose}
          className="rounded px-1.5 text-[12px] text-slate-400 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
        >
          Hide
        </button>
      </div>

      {settings.isLoading ? (
        <p className="text-[12px] text-slate-400">Loading settings…</p>
      ) : null}
      {settings.error ? (
        <p
          role="alert"
          className="text-[12px] text-rose-700 dark:text-rose-300"
        >
          Couldn't load the close settings: {settings.error.message}
        </p>
      ) : null}

      {draft ? (
        <form onSubmit={submit}>
          <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2 xl:grid-cols-4">
            {FIELDS.map((field) => {
              const value = draft[field.key]
              const id = `close-${field.key}`
              return (
                <div key={field.key} className="min-w-0">
                  <label
                    htmlFor={id}
                    className="block text-[12px] font-medium text-slate-200"
                  >
                    {field.label}
                  </label>
                  <div className="mt-1 flex items-center gap-1.5">
                    <input
                      id={id}
                      type="number"
                      inputMode="numeric"
                      required
                      min={field.min}
                      max={field.max}
                      step={1}
                      value={Number.isNaN(value) ? '' : value}
                      onChange={(event) =>
                        setDraft({
                          ...draft,
                          [field.key]: event.target.valueAsNumber,
                        })
                      }
                      aria-describedby={`${id}-help`}
                      className={input}
                    />
                    <span className="text-[12px] text-slate-400">
                      {field.unit}
                    </span>
                    {field.unit === 'min' && readable(value) ? (
                      <span className="font-mono text-[11px] text-slate-500">
                        = {readable(value)}
                      </span>
                    ) : null}
                  </div>
                  <p
                    id={`${id}-help`}
                    className="mt-0.5 text-[11px] text-slate-500"
                  >
                    {field.help}
                  </p>
                </div>
              )
            })}
            <div className="min-w-0">
              <label className="flex items-center gap-2 text-[12px] font-medium text-slate-200">
                <input
                  type="checkbox"
                  checked={draft.codex_close_inactive_enabled}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      codex_close_inactive_enabled: event.target.checked,
                    })
                  }
                  aria-describedby="close-codex-inactive-help"
                  className="h-3.5 w-3.5 accent-amber-400"
                />
                Close Codex sessions when Codex exits
              </label>
              <p
                id="close-codex-inactive-help"
                className="mt-0.5 text-[11px] text-slate-500"
              >
                Checked every 5 minutes against running Codex processes.
              </p>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={!changed || save.isPending}
              className={cn(
                'inline-flex h-8 items-center rounded-md border px-3 text-[12px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50',
                changed && !save.isPending
                  ? 'border-amber-500/50 bg-amber-500/15 text-amber-800 dark:text-amber-100 hover:bg-amber-500/25'
                  : 'cursor-not-allowed border-slate-800 text-slate-500',
              )}
            >
              {save.isPending ? 'Saving…' : 'Save'}
            </button>
            {changed && settings.data ? (
              <button
                type="button"
                onClick={() => setDraft(settings.data)}
                className="text-[12px] text-slate-400 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
              >
                Undo changes
              </button>
            ) : null}
            <p aria-live="polite" className="text-[12px]">
              {save.error ? (
                <span className="text-rose-700 dark:text-rose-300">
                  Not saved: {save.error.message}
                </span>
              ) : save.isSuccess && !changed ? (
                <span className="text-emerald-700 dark:text-emerald-300">
                  Saved. The reapers use it from their next run.
                </span>
              ) : null}
            </p>
          </div>
        </form>
      ) : null}
    </section>
  )
}
