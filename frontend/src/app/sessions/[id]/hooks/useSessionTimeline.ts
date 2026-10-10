'use client'

import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
} from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  TIMELINE_NOISE_TYPES,
  type TimelineServerState,
} from '@/components/timeline/event-timeline'
import {
  fetchSessionEvents,
  fetchSessionEventsSummary,
  type SessionEventsSummary,
} from '@/lib/api/sessions'
import type {
  SessionEventsResponse,
  SessionEventType,
  TimelineEvent,
} from '@/types/events'

export const TIMELINE_WINDOW = 500
export const SEARCH_DEBOUNCE_MS = 300
/** Upper bound on windows fetched for a typed scan (memory, usage). */
export const TYPED_SCAN_MAX_WINDOWS = 10

const KNOWN_EVENT_TYPES: SessionEventType[] = [
  'user_message',
  'assistant_message',
  'system_message',
  'thinking',
  'tool_use',
  'tool_result',
  'usage',
  'usage_counter',
  'memory_inject',
  'memory_cite',
  'error',
  'child_session_started',
  'child_session_update',
  'child_session_blocked',
  'child_session_result',
]

function eventTypeUniverse(summary: SessionEventsSummary | undefined) {
  return [
    ...new Set<string>([
      ...KNOWN_EVENT_TYPES,
      ...Object.keys(summary?.by_type ?? {}),
    ]),
  ].sort()
}

/** exclude_types for the timeline: selected chips win, otherwise hide noise. */
export function timelineExcludeTypes(
  selected: ReadonlySet<string>,
  includeNoise: boolean,
  universe: readonly string[],
): string[] {
  if (selected.size > 0) return universe.filter((type) => !selected.has(type))
  return includeNoise ? [] : [...TIMELINE_NOISE_TYPES]
}

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

function dedupeEvents(pages: SessionEventsResponse[]): TimelineEvent[] {
  const seen = new Set<string>()
  const out: TimelineEvent[] = []
  for (const page of pages) {
    for (const event of page.events) {
      if (seen.has(event.id)) continue
      seen.add(event.id)
      out.push(event)
    }
  }
  return out
}

export function useSessionEventsSummary(sessionId: string) {
  return useQuery({
    queryKey: ['session-events-summary', sessionId],
    queryFn: () => fetchSessionEventsSummary(sessionId),
  })
}

/** Oldest-first windowed timeline with server-side filters and search. */
export function useSessionTimeline(
  sessionId: string,
  summary: SessionEventsSummary | undefined,
) {
  const [selectedTypes, setSelectedTypes] = useState<Set<string>>(new Set())
  const [includeNoise, setIncludeNoise] = useState(false)
  const [search, setSearch] = useState('')
  const appliedSearch = useDebounced(search.trim(), SEARCH_DEBOUNCE_MS)

  const universe = useMemo(() => eventTypeUniverse(summary), [summary])
  const excludeTypes = useMemo(
    () => timelineExcludeTypes(selectedTypes, includeNoise, universe),
    [selectedTypes, includeNoise, universe],
  )

  const query = useInfiniteQuery({
    queryKey: ['session-events', sessionId, excludeTypes, appliedSearch],
    queryFn: ({ pageParam }) =>
      fetchSessionEvents(sessionId, {
        page_size: TIMELINE_WINDOW,
        exclude_types: excludeTypes,
        q: appliedSearch || undefined,
        after: pageParam || undefined,
      }),
    initialPageParam: '',
    getNextPageParam: (last) => last.next_after || undefined,
    placeholderData: keepPreviousData,
  })

  const pages = query.data?.pages ?? []
  const events = useMemo(() => dedupeEvents(pages), [pages])
  const firstPage = pages[0]
  const maxTurn = pages.length
    ? Math.max(...pages.map((page) => page.max_turn))
    : undefined

  const { fetchNextPage, hasNextPage, isFetchingNextPage } = query
  const loadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage)
      void fetchNextPage({ cancelRefetch: false })
  }, [fetchNextPage, hasNextPage, isFetchingNextPage])

  const toggleType = useCallback((type: string) => {
    setSelectedTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }, [])

  const server: TimelineServerState = {
    typeCounts: summary?.by_type ?? null,
    sessionTotal: summary?.total ?? null,
    matchingTotal: query.isPlaceholderData ? null : (firstPage?.total ?? null),
    selectedTypes,
    onToggleType: toggleType,
    onClearTypes: () => setSelectedTypes(new Set()),
    includeNoise,
    onToggleNoise: () => setIncludeNoise((value) => !value),
    search,
    onSearchChange: setSearch,
    appliedSearch,
    hasMore: !!hasNextPage,
    loadingMore: isFetchingNextPage,
    loadMoreFailed: query.isFetchNextPageError,
    onLoadMore: loadMore,
    refreshing: query.isPlaceholderData && query.isFetching,
  }

  return {
    events,
    hasData: !!query.data,
    maxTurn,
    isLoading: query.isLoading,
    error: query.error,
    isRefetchError: query.isRefetchError,
    refetch: query.refetch,
    server,
  }
}

/**
 * Loads only the given event types, oldest first, up to a bounded number of
 * windows. `complete` is false when more matching events exist than were read.
 */
export function useTypedEventScan(
  sessionId: string,
  types: readonly string[],
  summary: SessionEventsSummary | undefined,
  enabled: boolean,
) {
  const universe = eventTypeUniverse(summary)
  const exclude = universe.filter((type) => !types.includes(type))
  const expected = summary
    ? types.reduce((sum, type) => sum + (summary.by_type[type] ?? 0), 0)
    : null

  return useQuery({
    queryKey: ['session-events-scan', sessionId, [...types].sort()],
    enabled: enabled && !!summary && (expected ?? 0) > 0,
    queryFn: async () => {
      const events: TimelineEvent[] = []
      let after: string | undefined
      let total: number | null = null
      for (let window = 0; window < TYPED_SCAN_MAX_WINDOWS; window += 1) {
        const page = await fetchSessionEvents(sessionId, {
          page_size: TIMELINE_WINDOW,
          exclude_types: exclude,
          after,
        })
        total ??= page.total
        events.push(...page.events)
        after = page.next_after || undefined
        if (!after || page.events.length === 0) break
      }
      return {
        events,
        total: total ?? events.length,
        complete: !after,
      }
    },
  })
}
