import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { isAccountingWindow } from '@/lib/api/duration-split'
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

const SORT_FIELDS: readonly SortField[] = [
  'last_active',
  'status',
  'admin_share',
  'admin_tokens',
  'admin_duration',
]

function parseKinds(
  raw: string | null,
  fallback = DEFAULT_KINDS,
): SessionKind[] {
  if (raw === null) return fallback
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
  defaults = DEFAULT_LIST_STATE,
): SessionListState {
  const status = params.get('status') ?? ''
  const since = params.get('since') ?? ''
  const sort = params.get('sort') ?? ''
  const window = {
    start: params.get('accounting_start'),
    end: params.get('accounting_end'),
  }
  return {
    accountingWindow: isAccountingWindow(window) ? window : null,
    workRole: params.get('work_role') ?? '',
    harness: params.get('harness') ?? '',
    q: params.get('q') ?? '',
    kinds: parseKinds(params.get('kind'), defaults.kinds),
    status: STATUS_OPTIONS.some((option) => option.value === status)
      ? (status as StatusFilter)
      : DEFAULT_LIST_STATE.status,
    since: SINCE_OPTIONS.some((option) => option.value === since)
      ? (since as SincePreset)
      : DEFAULT_LIST_STATE.since,
    project: params.get('project') ?? '',
    model: params.get('model') ?? '',
    includeSubagents:
      params.get('subagents') !== null
        ? params.get('subagents') === '1'
        : defaults.includeSubagents,
    includeBenchmarks:
      params.get('benchmarks') !== null
        ? params.get('benchmarks') === '1'
        : defaults.includeBenchmarks,
    sort: SORT_FIELDS.includes(sort as SortField)
      ? (sort as SortField)
      : DEFAULT_LIST_STATE.sort,
    selected: params.get('sel') || null,
  }
}

/** Only non-default values are written, so the bare /sessions URL is the default view. */
export function serializeSessionListState(
  state: SessionListState,
  defaults = DEFAULT_LIST_STATE,
): URLSearchParams {
  const params = new URLSearchParams()
  if (state.accountingWindow) {
    params.set('accounting_start', state.accountingWindow.start)
    params.set('accounting_end', state.accountingWindow.end)
  }
  if (state.workRole) params.set('work_role', state.workRole)
  if (state.harness) params.set('harness', state.harness)
  if (state.q) params.set('q', state.q)
  if (!sameKinds(state.kinds, defaults.kinds)) {
    params.set(
      'kind',
      sameKinds(state.kinds, SESSION_KINDS) ? 'all' : state.kinds.join(','),
    )
  }
  if (state.status) params.set('status', state.status)
  if (state.since !== DEFAULT_LIST_STATE.since) params.set('since', state.since)
  if (state.project) params.set('project', state.project)
  if (state.model) params.set('model', state.model)
  if (state.includeSubagents !== defaults.includeSubagents)
    params.set('subagents', state.includeSubagents ? '1' : '0')
  if (state.includeBenchmarks !== defaults.includeBenchmarks)
    params.set('benchmarks', state.includeBenchmarks ? '1' : '0')
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
    !state.workRole &&
    !state.harness &&
    !state.includeSubagents &&
    !state.includeBenchmarks
  )
}

/** Cross-route links make default scope explicit as routes have different defaults. */
export function sessionScopeParams(state: SessionListState): URLSearchParams {
  const params = serializeSessionListState(state)
  params.set(
    'kind',
    sameKinds(state.kinds, SESSION_KINDS) ? 'all' : state.kinds.join(','),
  )
  params.set('subagents', state.includeSubagents ? '1' : '0')
  params.set('benchmarks', state.includeBenchmarks ? '1' : '0')
  return params
}

/**
 * The URL is the only store for list state. Filter edits replace the current
 * history entry; opening a preview pushes one so Back closes it.
 */
export function useSessionListState(defaults = DEFAULT_LIST_STATE) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const searchKey = searchParams.toString()
  const [initialWindow] = useState(() => accountingWindowForHours(24))

  const state = useMemo(() => {
    const parsed = parseSessionListState(
      new URLSearchParams(searchKey),
      defaults,
    )
    return {
      ...parsed,
      accountingWindow: parsed.accountingWindow ?? initialWindow,
    }
  }, [searchKey, defaults, initialWindow])

  const navigate = useCallback(
    (next: SessionListState, mode: 'push' | 'replace') => {
      const query = serializeSessionListState(next, defaults).toString()
      const href = query ? `${pathname}?${query}` : pathname
      if (mode === 'push') router.push(href, { scroll: false })
      else router.replace(href, { scroll: false })
    },
    [pathname, router, defaults],
  )

  useEffect(() => {
    const params = new URLSearchParams(searchKey)
    if (
      !isAccountingWindow({
        start: params.get('accounting_start'),
        end: params.get('accounting_end'),
      })
    )
      navigate(state, 'replace')
  }, [navigate, searchKey, state])

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
      {
        ...defaults,
        accountingWindow: state.accountingWindow,
        sort: state.sort,
        selected: state.selected,
      },
      'replace',
    )
  }, [navigate, defaults, state.accountingWindow, state.selected, state.sort])

  return { state, update, select, clearFilters }
}

export function accountingWindowForHours(hours: number) {
  const end = new Date()
  return {
    start: new Date(end.getTime() - hours * 3_600_000).toISOString(),
    end: end.toISOString(),
  }
}
