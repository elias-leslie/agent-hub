import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
} from '@tanstack/react-query'
import { useMemo } from 'react'
import {
  fetchSessionFacets,
  querySessions,
  type SessionListItem,
  type SessionListQuery,
} from '@/lib/api/sessions'
import type { SessionListState } from '../types'
import { sinceToIso } from '../utils'

/** Background tabs do not poll: react-query pauses intervals while hidden. */
const SESSIONS_REFRESH_INTERVAL_MS = 10_000
const PAGE_SIZE = 100

type FilterQuery = Omit<
  SessionListQuery,
  'cursor' | 'page_size' | 'sort_by' | 'sort_direction'
>

export function toFilterQuery(state: SessionListState): FilterQuery {
  return {
    accounting_start: state.accountingWindow?.start,
    accounting_end: state.accountingWindow?.end,
    work_role: state.workRole || undefined,
    harness: state.harness || undefined,
    q: state.q.trim() || undefined,
    kind: state.kinds,
    status: state.status || undefined,
    since: sinceToIso(
      state.since,
      state.accountingWindow ? new Date(state.accountingWindow.end) : undefined,
    ),
    project_id: state.project || undefined,
    model: state.model || undefined,
    roots_only: !state.includeSubagents,
    exclude_benchmarks: !state.includeBenchmarks,
  }
}

/** Stable cache identity: the since preset, not the moving ISO timestamp. */
function filterKey(state: SessionListState) {
  return {
    q: state.q.trim(),
    kinds: [...state.kinds].sort(),
    status: state.status,
    since: state.since,
    project: state.project,
    model: state.model,
    subagents: state.includeSubagents,
    benchmarks: state.includeBenchmarks,
    accountingWindow: state.accountingWindow,
    workRole: state.workRole,
    harness: state.harness,
  }
}

export function useSessionsData(state: SessionListState) {
  const key = filterKey(state)

  const list = useInfiniteQuery({
    queryKey: ['sessions', 'list', key, state.sort],
    queryFn: ({ pageParam }) =>
      querySessions({
        ...toFilterQuery(state),
        sort_by: state.sort,
        sort_direction: state.sort === 'status' ? 'asc' : 'desc',
        cursor: pageParam,
        page_size: PAGE_SIZE,
      }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    placeholderData: keepPreviousData,
    refetchInterval: SESSIONS_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: false,
  })

  const facets = useQuery({
    queryKey: ['sessions', 'facets', key],
    queryFn: () => fetchSessionFacets(toFilterQuery(state)),
    placeholderData: keepPreviousData,
    refetchInterval: SESSIONS_REFRESH_INTERVAL_MS,
    refetchIntervalInBackground: false,
  })

  // A refetch of several keyset pages can briefly overlap; keep the first copy.
  const sessions = useMemo(() => {
    const seen = new Set<string>()
    const rows: SessionListItem[] = []
    for (const page of list.data?.pages ?? []) {
      for (const session of page.sessions) {
        if (seen.has(session.id)) continue
        seen.add(session.id)
        rows.push(session)
      }
    }
    return rows
  }, [list.data])

  return {
    sessions,
    total: list.data?.pages[0]?.total ?? 0,
    hasData: Boolean(list.data),
    isLoading: list.isLoading,
    isFetching: list.isFetching,
    isPlaceholder: list.isPlaceholderData,
    error: list.error,
    fetchNextPage: list.fetchNextPage,
    hasNextPage: Boolean(list.hasNextPage),
    isFetchingNextPage: list.isFetchingNextPage,
    refetch: list.refetch,
    facets: facets.data ?? null,
    facetsError: facets.error,
    accountingWindow:
      list.data?.pages[0]?.accounting_window ?? state.accountingWindow,
    workRoles: facets.data?.work_roles ?? list.data?.pages[0]?.work_roles ?? [],
    harnesses: facets.data?.harnesses ?? list.data?.pages[0]?.harnesses ?? [],
  }
}
