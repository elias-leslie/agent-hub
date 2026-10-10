import { RefreshCw, Search } from 'lucide-react'
import { type RefObject, useEffect, useRef, useState } from 'react'
import {
  SESSION_KINDS,
  type SessionFacets,
  type SessionKind,
} from '@/lib/api/sessions'
import { cn } from '@/lib/utils'
import {
  KIND_LABELS,
  type SessionListState,
  SINCE_OPTIONS,
  type SortField,
  STATUS_OPTIONS,
} from '../types'
import { ModelFilterBadge } from './ModelFilterBadge'

const COUNT = new Intl.NumberFormat('en-US')
const SEARCH_DEBOUNCE_MS = 250

const chip =
  'inline-flex h-7 items-center gap-1.5 rounded-md border px-2 text-[12px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50'
const chipOff =
  'border-slate-800 bg-slate-950/60 text-slate-400 hover:border-slate-700 hover:text-slate-200'
const chipOn = 'border-amber-500/40 bg-amber-500/10 text-amber-100'
const control =
  'h-7 rounded-md border border-slate-800 bg-slate-950/60 px-2 text-[12px] text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50'

function Count({ value }: { value: number | undefined }) {
  if (value === undefined) return null
  return (
    <span className="font-mono text-[11px] tabular-nums text-slate-500">
      {COUNT.format(value)}
    </span>
  )
}

function statusCount(
  facets: SessionFacets | null,
  value: string,
): number | undefined {
  if (!facets) return undefined
  const counts = facets.status
  if (value === '') {
    return Object.entries(counts)
      .filter(([key]) => key !== 'running')
      .reduce((sum, [, count]) => sum + count, 0)
  }
  if (value === 'running') return counts.running ?? counts.active
  return counts[value] ?? 0
}

export function SessionsToolbar({
  state,
  facets,
  total,
  isFetching,
  searchRef,
  onChange,
  onRefresh,
}: {
  state: SessionListState
  facets: SessionFacets | null
  total: number
  isFetching: boolean
  searchRef: RefObject<HTMLInputElement | null>
  onChange: (patch: Partial<SessionListState>) => void
  onRefresh: () => void
}) {
  const [query, setQuery] = useState(state.q)
  const lastSent = useRef(state.q)

  // Back/forward or "clear filters" changes the URL under the input.
  useEffect(() => {
    if (state.q !== lastSent.current) {
      lastSent.current = state.q
      setQuery(state.q)
    }
  }, [state.q])

  useEffect(() => {
    if (query === lastSent.current) return
    const timer = setTimeout(() => {
      lastSent.current = query
      onChange({ q: query })
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [onChange, query])

  const toggleKind = (kind: SessionKind) => {
    const kinds = state.kinds.includes(kind)
      ? state.kinds.filter((value) => value !== kind)
      : [...state.kinds, kind]
    // An empty set would show nothing; treat it as "all kinds".
    onChange({ kinds: kinds.length > 0 ? kinds : [...SESSION_KINDS] })
  }

  const projectOptions = facets?.projects ?? []
  const projectMissing =
    state.project !== '' &&
    !projectOptions.some((option) => option.project_id === state.project)

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-1 text-base font-semibold tracking-tight text-slate-100">
          Sessions
        </h1>
        <span
          className="font-mono text-[12px] tabular-nums text-slate-400"
          data-testid="sessions-total-count"
        >
          {COUNT.format(total)} matching
        </span>
        <div className="relative ml-auto min-w-[12rem] flex-1 sm:max-w-sm">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <input
            ref={searchRef}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search id, task, prompt summary, branch, agent…"
            aria-label="Search sessions"
            aria-keyshortcuts="/"
            className={cn(control, 'h-8 w-full pl-7')}
          />
        </div>
        <button
          type="button"
          onClick={onRefresh}
          aria-label="Refresh sessions"
          title="Refresh (updates every 10s while this tab is visible)"
          className={cn(chip, chipOff, 'h-8')}
        >
          <RefreshCw
            className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')}
          />
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <fieldset className="flex flex-wrap items-center gap-1">
          <legend className="sr-only">Kind</legend>
          {SESSION_KINDS.map((kind) => {
            const on = state.kinds.includes(kind)
            return (
              <button
                key={kind}
                type="button"
                aria-pressed={on}
                onClick={() => toggleKind(kind)}
                className={cn(chip, on ? chipOn : chipOff)}
              >
                {KIND_LABELS[kind]}
                <Count value={facets?.kind[kind]} />
              </button>
            )
          })}
        </fieldset>

        <fieldset className="flex items-center rounded-md border border-slate-800 p-0.5">
          <legend className="sr-only">Status</legend>
          {STATUS_OPTIONS.map((option) => {
            const on = state.status === option.value
            return (
              <button
                key={option.value || 'all'}
                type="button"
                aria-pressed={on}
                onClick={() => onChange({ status: option.value })}
                className={cn(
                  'inline-flex h-6 items-center gap-1.5 rounded px-2 text-[12px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50',
                  on
                    ? 'bg-slate-800 text-slate-100'
                    : 'text-slate-400 hover:text-slate-200',
                )}
              >
                {option.label}
                <Count value={statusCount(facets, option.value)} />
              </button>
            )
          })}
        </fieldset>

        <label className="flex items-center gap-1.5 text-[12px] text-slate-400">
          <span>Active</span>
          <select
            value={state.since}
            onChange={(event) =>
              onChange({
                since: event.target.value as SessionListState['since'],
              })
            }
            className={control}
          >
            {SINCE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-1.5 text-[12px] text-slate-400">
          <span>Project</span>
          <select
            value={state.project}
            onChange={(event) => onChange({ project: event.target.value })}
            className={cn(control, 'max-w-[12rem]')}
          >
            <option value="">All projects</option>
            {projectMissing ? (
              <option value={state.project}>{state.project} (0)</option>
            ) : null}
            {projectOptions.map((option) => (
              <option key={option.project_id} value={option.project_id}>
                {option.project_id} ({COUNT.format(option.count)})
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-1.5 text-[12px] text-slate-400">
          <input
            type="checkbox"
            checked={state.includeSubagents}
            onChange={(event) =>
              onChange({ includeSubagents: event.target.checked })
            }
            className="h-3.5 w-3.5 accent-amber-400"
          />
          Include sub-agents
        </label>

        <label className="flex items-center gap-1.5 text-[12px] text-slate-400">
          <input
            type="checkbox"
            checked={state.includeBenchmarks}
            onChange={(event) =>
              onChange({ includeBenchmarks: event.target.checked })
            }
            className="h-3.5 w-3.5 accent-amber-400"
          />
          Include benchmarks
        </label>

        <label className="flex items-center gap-1.5 text-[12px] text-slate-400 sm:ml-auto">
          <span>Sort</span>
          <select
            value={state.sort}
            onChange={(event) =>
              onChange({ sort: event.target.value as SortField })
            }
            className={control}
          >
            <option value="last_active">Last active</option>
            <option value="status">Status</option>
          </select>
        </label>

        {state.model ? (
          <ModelFilterBadge
            modelFilter={state.model}
            onClear={() => onChange({ model: '' })}
          />
        ) : null}
      </div>
    </div>
  )
}
