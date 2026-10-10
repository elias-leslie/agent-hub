'use client'

import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
} from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  fetchSession,
  fetchSessionEvents,
  querySessions,
  type SessionListItem,
} from '@/lib/api/sessions'
import type { SessionEventsResponse, TimelineEvent } from '@/types/events'

export const LOG_WINDOW = 300
export const LOG_REFRESH_MS = 10_000
export const SEARCH_DEBOUNCE_MS = 300
export const CHILD_PAGE_SIZE = 100
/** Children beyond this many pages are counted but not placed in the log. */
export const CHILD_MAX_PAGES = 5

/** Never useful in the log: child bookkeeping is read from the child list. */
export const ALWAYS_EXCLUDED = [
  'child_session_update',
  'child_session_started',
  'child_session_result',
  'usage_counter',
] as const
/** Shown only when Details is on. */
export const DETAIL_TYPES = [
  'thinking',
  'usage',
  'memory_inject',
  'memory_cite',
] as const

export function logExcludeTypes(details: boolean): string[] {
  return details ? [...ALWAYS_EXCLUDED] : [...ALWAYS_EXCLUDED, ...DETAIL_TYPES]
}

export function isLiveStatus(status: string | null | undefined): boolean {
  return status === 'active' || status === 'running'
}

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

/** Newest-first pages flattened to chronological order without duplicates. */
export function chronological(pages: SessionEventsResponse[]): TimelineEvent[] {
  const seen = new Set<string>()
  const out: TimelineEvent[] = []
  for (const page of pages) {
    for (const event of page.events) {
      if (seen.has(event.id)) continue
      seen.add(event.id)
      out.push(event)
    }
  }
  return out.sort((a, b) => a.turn - b.turn || a.sequence - b.sequence)
}

export function useSessionDetail(sessionId: string, live: boolean) {
  return useQuery({
    queryKey: ['session', sessionId, { includeEvents: false }],
    queryFn: () => fetchSession(sessionId, { includeEvents: false }),
    refetchInterval: live ? LOG_REFRESH_MS : false,
    refetchIntervalInBackground: false,
  })
}

/**
 * Event log for one session: newest window first, older windows on demand.
 * Details and search are applied by the server so windows hold only rows
 * the person will see.
 */
export function useSessionLog(
  sessionId: string,
  options: { details: boolean; search: string; live: boolean },
) {
  const appliedSearch = useDebounced(options.search.trim(), SEARCH_DEBOUNCE_MS)
  const excludeTypes = useMemo(
    () => logExcludeTypes(options.details),
    [options.details],
  )

  const query = useInfiniteQuery({
    queryKey: ['session-log', sessionId, excludeTypes, appliedSearch],
    queryFn: ({ pageParam }) =>
      fetchSessionEvents(sessionId, {
        page_size: LOG_WINDOW,
        order: 'desc',
        exclude_types: excludeTypes,
        q: appliedSearch || undefined,
        after: pageParam || undefined,
      }),
    initialPageParam: '',
    getNextPageParam: (last) => last.next_after || undefined,
    placeholderData: keepPreviousData,
  })

  // Live runs poll only the newest window and merge it in by id; refetching
  // the infinite query would re-read every loaded window.
  const latest = useQuery({
    queryKey: ['session-log-latest', sessionId, excludeTypes, appliedSearch],
    enabled: options.live && !!query.data,
    queryFn: () =>
      fetchSessionEvents(sessionId, {
        page_size: LOG_WINDOW,
        order: 'desc',
        exclude_types: excludeTypes,
        q: appliedSearch || undefined,
      }),
    refetchInterval: LOG_REFRESH_MS,
    refetchIntervalInBackground: false,
  })

  const pages = query.data?.pages ?? []
  const latestPage = options.live ? latest.data : undefined
  const events = useMemo(
    () => chronological(latestPage ? [latestPage, ...pages] : pages),
    [pages, latestPage],
  )
  const total = query.isPlaceholderData
    ? null
    : (latestPage?.total ?? pages[0]?.total ?? null)

  const { fetchNextPage, hasNextPage, isFetchingNextPage } = query
  const loadEarlier = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage)
      void fetchNextPage({ cancelRefetch: false })
  }, [fetchNextPage, hasNextPage, isFetchingNextPage])

  return {
    events,
    total,
    maxTurn: pages[0]?.max_turn,
    appliedSearch,
    hasData: !!query.data,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
    hasEarlier: !!hasNextPage,
    loadingEarlier: isFetchingNextPage,
    loadEarlierFailed: query.isFetchNextPageError,
    loadEarlier,
    refreshing: query.isPlaceholderData && query.isFetching,
  }
}

/**
 * All children of a session in start order. The server's `time` sort is last
 * activity, which moves while children run, so pages are de-duplicated and
 * re-sorted by start time here. `complete` is false when more exist.
 */
export function useSessionChildren(
  sessionId: string,
  childCount: number,
  activeChildren: number,
) {
  return useQuery({
    queryKey: ['session-children', sessionId],
    enabled: childCount > 0,
    refetchInterval: activeChildren > 0 ? LOG_REFRESH_MS : false,
    refetchIntervalInBackground: false,
    queryFn: async () => {
      const children: SessionListItem[] = []
      let cursor: string | undefined
      let total = 0
      for (let page = 0; page < CHILD_MAX_PAGES; page += 1) {
        const response = await querySessions({
          parent_session_id: sessionId,
          sort_by: 'time',
          sort_direction: 'asc',
          page_size: CHILD_PAGE_SIZE,
          cursor,
        })
        total = response.total
        children.push(...response.sessions)
        cursor = response.next_cursor ?? undefined
        if (!cursor || response.sessions.length === 0) break
      }
      const unique = [
        ...new Map(children.map((child) => [child.id, child])).values(),
      ]
      unique.sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at))
      return { children: unique, total, complete: !cursor }
    },
  })
}
