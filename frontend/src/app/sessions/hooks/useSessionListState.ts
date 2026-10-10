import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useMemo } from 'react'
import { SESSION_KINDS, type SessionKind } from '@/lib/api/sessions'
import {
  DEFAULT_KINDS,
  DEFAULT_LIST_STATE,
  type SessionListState,
  SINCE_OPTIONS,
  type SincePreset,
  type SortField,
  STATUS_OPTIONS,
  type StatusFilter,
} from '../types'

const SORT_FIELDS: readonly SortField[] = ['last_active', 'status']

function parseKinds(raw: string | null): SessionKind[] {
  if (raw === null) return DEFAULT_KINDS
  if (raw === 'all') return [...SESSION_KINDS]
  const kinds = raw
    .split(',')
    .filter((kind): kind is SessionKind =>
      SESSION_KINDS.includes(kind as SessionKind),
    )
  return kinds.length > 0 ? kinds : DEFAULT_KINDS
}

function sameKinds(a: readonly SessionKind[], b: readonly SessionKind[]) {
  return a.length === b.length && a.every((kind) => b.includes(kind))
}

export function parseSessionListState(
  params: Pick<URLSearchParams, 'get'>,
): SessionListState {
  const status = params.get('status') ?? ''
  const since = params.get('since') ?? ''
  const sort = params.get('sort') ?? ''
  return {
    q: params.get('q') ?? '',
    kinds: parseKinds(params.get('kind')),
    status: STATUS_OPTIONS.some((option) => option.value === status)
      ? (status as StatusFilter)
      : DEFAULT_LIST_STATE.status,
    since: SINCE_OPTIONS.some((option) => option.value === since)
      ? (since as SincePreset)
      : DEFAULT_LIST_STATE.since,
    project: params.get('project') ?? '',
    model: params.get('model') ?? '',
    includeSubagents: params.get('subagents') === '1',
    includeBenchmarks: params.get('benchmarks') === '1',
    sort: SORT_FIELDS.includes(sort as SortField)
      ? (sort as SortField)
      : DEFAULT_LIST_STATE.sort,
    selected: params.get('sel') || null,
  }
}

/** Only non-default values are written, so the bare /sessions URL is the default view. */
export function serializeSessionListState(
  state: SessionListState,
): URLSearchParams {
  const params = new URLSearchParams()
  if (state.q) params.set('q', state.q)
  if (!sameKinds(state.kinds, DEFAULT_KINDS)) {
    params.set(
      'kind',
      sameKinds(state.kinds, SESSION_KINDS) ? 'all' : state.kinds.join(','),
    )
  }
  if (state.status) params.set('status', state.status)
  if (state.since !== DEFAULT_LIST_STATE.since) params.set('since', state.since)
  if (state.project) params.set('project', state.project)
  if (state.model) params.set('model', state.model)
  if (state.includeSubagents) params.set('subagents', '1')
  if (state.includeBenchmarks) params.set('benchmarks', '1')
  if (state.sort !== DEFAULT_LIST_STATE.sort) params.set('sort', state.sort)
  if (state.selected) params.set('sel', state.selected)
  return params
}

export function isDefaultFilterState(state: SessionListState): boolean {
  return (
    !state.q &&
    sameKinds(state.kinds, DEFAULT_KINDS) &&
    !state.status &&
    state.since === DEFAULT_LIST_STATE.since &&
    !state.project &&
    !state.model &&
    !state.includeSubagents &&
    !state.includeBenchmarks
  )
}

/**
 * The URL is the only store for list state. Filter edits replace the current
 * history entry; opening a preview pushes one so Back closes it.
 */
export function useSessionListState() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const searchKey = searchParams.toString()

  const state = useMemo(
    () => parseSessionListState(new URLSearchParams(searchKey)),
    [searchKey],
  )

  const navigate = useCallback(
    (next: SessionListState, mode: 'push' | 'replace') => {
      const query = serializeSessionListState(next).toString()
      const href = query ? `${pathname}?${query}` : pathname
      if (mode === 'push') router.push(href, { scroll: false })
      else router.replace(href, { scroll: false })
    },
    [pathname, router],
  )

  const update = useCallback(
    (patch: Partial<SessionListState>) => {
      navigate({ ...state, ...patch }, 'replace')
    },
    [navigate, state],
  )

  const select = useCallback(
    (sessionId: string | null) => {
      if (sessionId === state.selected) return
      // Moving between rows while a preview is open is not a new history step.
      const mode = state.selected === null && sessionId ? 'push' : 'replace'
      navigate({ ...state, selected: sessionId }, mode)
    },
    [navigate, state],
  )

  const clearFilters = useCallback(() => {
    navigate(
      { ...DEFAULT_LIST_STATE, sort: state.sort, selected: state.selected },
      'replace',
    )
  }, [navigate, state.selected, state.sort])

  return { state, update, select, clearFilters }
}
