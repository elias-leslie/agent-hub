'use client'

import { useVirtualizer } from '@tanstack/react-virtual'
import { Database, GitFork, Loader2, Search, X } from 'lucide-react'
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import type { SessionTimelineEvent } from '@/lib/api'
import type { NativeCommandEvidence } from '@/lib/api/native-evidence'
import { cn } from '@/lib/utils'
import { EVENT_CONFIGS, getEventConfig } from './event-config'
import { EventItem } from './event-item'
import { FilterChip } from './filter-chip'
import { TurnHeader } from './turn-group'

type EventType = SessionTimelineEvent['event_type']

/** Event types hidden by default in server-windowed timelines. */
export const TIMELINE_NOISE_TYPES = [
  'child_session_update',
  'usage_counter',
] as const

/** Rows above this count are virtualized. Small timelines render in flow. */
export const VIRTUALIZE_MIN_ROWS = 60

/**
 * Server-driven timeline state. When provided, filtering, search and counts
 * come from the server and the timeline renders `events` as already filtered.
 */
export interface TimelineServerState {
  /** Per-type counts for the whole session (events summary); null if unavailable. */
  typeCounts: Record<string, number> | null
  /** Total events in the session (events summary); null if unavailable. */
  sessionTotal: number | null
  /** Total events matching the current filters and search; null if unknown. */
  matchingTotal: number | null
  selectedTypes: ReadonlySet<string>
  onToggleType: (eventType: string) => void
  onClearTypes: () => void
  includeNoise: boolean
  onToggleNoise: () => void
  /** Search input value (applied to the server after a debounce). */
  search: string
  onSearchChange: (query: string) => void
  /** Search term the loaded events were fetched with. */
  appliedSearch: string
  hasMore: boolean
  loadingMore: boolean
  loadMoreFailed?: boolean
  onLoadMore: () => void
  /** Filters changed and the first window is being fetched. */
  refreshing?: boolean
}

interface EventTimelineProps {
  events: SessionTimelineEvent[]
  className?: string
  density?: 'default' | 'compact'
  nativeCommands?: NativeCommandEvidence[]
  server?: TimelineServerState
}

const CLIENT_CHIP_TYPES: EventType[] = [
  'user_message',
  'assistant_message',
  'thinking',
  'tool_use',
  'tool_result',
  'memory_inject',
  'memory_cite',
  'error',
]

const SERVER_CHIP_TYPES: string[] = [
  'user_message',
  'assistant_message',
  'system_message',
  'thinking',
  'tool_use',
  'tool_result',
  'usage',
  'memory_inject',
  'memory_cite',
  'error',
  'child_session_started',
  'child_session_blocked',
  'child_session_result',
]

type Row =
  | {
      kind: 'turn'
      key: string
      turn: number
      count: number
      collapsed: boolean
      incomplete: boolean
    }
  | {
      kind: 'event'
      key: string
      event: SessionTimelineEvent
      isFirst: boolean
      isLast: boolean
    }

function matchesSearch(event: SessionTimelineEvent, query: string) {
  return (
    event.content?.toLowerCase().includes(query) ||
    event.tool_name?.toLowerCase().includes(query) ||
    event.agent_name?.toLowerCase().includes(query) ||
    JSON.stringify(event.tool_input)?.toLowerCase().includes(query) ||
    JSON.stringify(event.tool_output)?.toLowerCase().includes(query)
  )
}

function countByType(events: SessionTimelineEvent[]) {
  const counts: Record<string, number> = {}
  for (const event of events) {
    counts[event.event_type] = (counts[event.event_type] || 0) + 1
  }
  return counts
}

function n(value: number) {
  return value.toLocaleString()
}

export function EventTimeline({
  events,
  className,
  density = 'default',
  nativeCommands,
  server,
}: EventTimelineProps) {
  const [clientSearch, setClientSearch] = useState('')
  const [clientFilters, setClientFilters] = useState<Set<string>>(new Set())
  const [collapsedTurns, setCollapsedTurns] = useState<Set<number>>(new Set())
  const compact = density === 'compact'
  const scrollRef = useRef<HTMLDivElement>(null)
  const loadMoreRef = useRef<HTMLDivElement>(null)

  const commandByEvent = useMemo(() => {
    const map = new Map<string, NativeCommandEvidence[]>()
    for (const command of nativeCommands ?? []) {
      for (const id of command.projection_event_ids) {
        map.set(id, [...(map.get(id) ?? []), command])
      }
    }
    return map
  }, [nativeCommands])

  const loadedCounts = useMemo(() => countByType(events), [events])
  const searchValue = server ? server.search : clientSearch
  const setSearchValue = server ? server.onSearchChange : setClientSearch
  const activeFilters = server ? server.selectedTypes : clientFilters
  const countsFromServer = !!server?.typeCounts
  const chipCounts = server?.typeCounts ?? loadedCounts

  // Server mode renders events as delivered; client mode filters locally.
  const visibleEvents = useMemo(() => {
    if (server) return events
    const query = clientSearch.toLowerCase()
    return events.filter((event) => {
      if (clientFilters.size > 0 && !clientFilters.has(event.event_type)) {
        return false
      }
      return query ? matchesSearch(event, query) : true
    })
  }, [server, events, clientFilters, clientSearch])

  const groupedByTurn = useMemo(() => {
    const groups = new Map<number, SessionTimelineEvent[]>()
    for (const event of visibleEvents) {
      const existing = groups.get(event.turn)
      if (existing) existing.push(event)
      else groups.set(event.turn, [event])
    }
    return Array.from(groups.entries()).sort((a, b) => a[0] - b[0])
  }, [visibleEvents])

  const hasMore = !!server?.hasMore
  const rows = useMemo(() => {
    const out: Row[] = []
    groupedByTurn.forEach(([turn, turnEvents], groupIndex) => {
      const lastGroup = groupIndex === groupedByTurn.length - 1
      const collapsed = collapsedTurns.has(turn)
      out.push({
        kind: 'turn',
        key: `turn-${turn}`,
        turn,
        count: turnEvents.length,
        collapsed,
        incomplete: lastGroup && hasMore,
      })
      if (collapsed) return
      turnEvents.forEach((event, idx) => {
        out.push({
          kind: 'event',
          key: event.id,
          event,
          isFirst: idx === 0,
          isLast: idx === turnEvents.length - 1 && lastGroup,
        })
      })
    })
    return out
  }, [groupedByTurn, collapsedTurns, hasMore])

  const virtualize = rows.length > VIRTUALIZE_MIN_ROWS
  const virtualizer = useVirtualizer({
    count: rows.length,
    enabled: virtualize,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) =>
      rows[index]?.kind === 'turn' ? 48 : compact ? 76 : 112,
    getItemKey: (index) => rows[index]?.key ?? index,
    overscan: 8,
    initialRect: { width: 960, height: 900 },
  })
  const virtualItems = virtualize ? virtualizer.getVirtualItems() : []
  const lastVirtualIndex = virtualItems.at(-1)?.index ?? -1

  const canAutoLoad =
    !!server &&
    server.hasMore &&
    !server.loadingMore &&
    !server.loadMoreFailed &&
    !server.refreshing
  const onLoadMore = server?.onLoadMore

  // Virtualized: load the next window when the rendered range nears the end.
  useEffect(() => {
    if (!virtualize || !canAutoLoad || !onLoadMore) return
    if (lastVirtualIndex >= rows.length - 15) onLoadMore()
  }, [virtualize, canAutoLoad, onLoadMore, lastVirtualIndex, rows.length])

  // In flow: load when the end-of-list control scrolls into view.
  useEffect(() => {
    if (virtualize || !canAutoLoad || !onLoadMore) return
    const node = loadMoreRef.current
    if (!node || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onLoadMore()
      },
      { root: scrollRef.current, rootMargin: '400px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [virtualize, canAutoLoad, onLoadMore])

  const toggleTurn = (turn: number) => {
    setCollapsedTurns((prev) => {
      const next = new Set(prev)
      if (next.has(turn)) next.delete(turn)
      else next.add(turn)
      return next
    })
  }

  const toggleFilter = (eventType: string) => {
    if (server) {
      server.onToggleType(eventType)
      return
    }
    setClientFilters((prev) => {
      const next = new Set(prev)
      if (next.has(eventType)) next.delete(eventType)
      else next.add(eventType)
      return next
    })
  }
  const clearFilters = () => {
    if (server) server.onClearTypes()
    else setClientFilters(new Set())
  }

  const chipTypes = (server ? SERVER_CHIP_TYPES : CLIENT_CHIP_TYPES).filter(
    (type) => (chipCounts[type] ?? 0) > 0 || activeFilters.has(type),
  )
  const noiseCount = server
    ? TIMELINE_NOISE_TYPES.reduce(
        (sum, type) => sum + (server.typeCounts?.[type] ?? 0),
        0,
      )
    : 0
  const showNoiseChip =
    !!server && (server.typeCounts === null || noiseCount > 0)
  const countScope = countsFromServer
    ? 'events in this session'
    : 'loaded events'

  const renderRow = (row: Row): ReactNode =>
    row.kind === 'turn' ? (
      <div className="pb-3 pt-1">
        <TurnHeader
          turn={row.turn}
          count={row.count}
          collapsed={row.collapsed}
          incomplete={row.incomplete}
          sticky={!virtualize}
          onToggle={() => toggleTurn(row.turn)}
        />
      </div>
    ) : (
      <div className="pl-2">
        <EventItem
          event={row.event}
          nativeCommands={commandByEvent.get(row.event.id)}
          isFirst={row.isFirst}
          isLast={row.isLast}
        />
      </div>
    )

  const filtering =
    activeFilters.size > 0 || (server ? !!server.appliedSearch : !!clientSearch)

  return (
    <div className={cn('flex flex-col h-full min-h-0', className)}>
      {/* Filters header */}
      <div
        className={cn(
          'sticky top-0 z-20 border-b border-slate-800/60 bg-slate-950/95 backdrop-blur-sm',
          compact ? 'flex flex-wrap items-center gap-2 p-2' : 'space-y-3 p-4',
        )}
      >
        <div
          className={cn(
            'relative',
            compact ? 'min-w-0 flex-1 basis-[220px]' : 'w-full',
          )}
        >
          <Search
            aria-hidden
            className={cn(
              'absolute left-3 top-1/2 -translate-y-1/2 text-slate-500',
              compact ? 'h-3 w-3' : 'h-4 w-4',
            )}
          />
          <input
            aria-label="Search session events"
            type="search"
            value={searchValue}
            onChange={(e) => setSearchValue(e.target.value)}
            placeholder={
              server
                ? 'Search all events in this session...'
                : 'Search events...'
            }
            className={cn(
              'w-full rounded-lg pl-9 pr-9',
              compact ? 'py-1.5 text-xs' : 'py-2 text-sm',
              'bg-slate-900/60 border border-slate-800/60',
              'text-slate-300 placeholder:text-slate-600',
              'focus:outline-none focus:ring-2 focus:ring-sky-400/60 focus:border-slate-700',
              'transition-all duration-200 [&::-webkit-search-cancel-button]:hidden',
            )}
          />
          {searchValue && (
            <button
              type="button"
              aria-label="Clear event search"
              onClick={() => setSearchValue('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-slate-500 hover:text-slate-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              <X className="w-4 h-4" aria-hidden />
            </button>
          )}
        </div>

        <div className={cn('flex flex-wrap', compact ? 'gap-1.5' : 'gap-2')}>
          {chipTypes.map((eventType) => (
            <FilterChip
              key={eventType}
              label={EVENT_CONFIGS[eventType]?.label || eventType}
              eventType={eventType as EventType}
              isActive={activeFilters.has(eventType)}
              count={chipCounts[eventType] || 0}
              countLabel={`${n(chipCounts[eventType] || 0)} ${countScope}`}
              compact={compact}
              onClick={() => toggleFilter(eventType)}
            />
          ))}

          {showNoiseChip && server && (
            <button
              type="button"
              aria-pressed={server.includeNoise}
              onClick={server.onToggleNoise}
              disabled={activeFilters.size > 0}
              title={
                activeFilters.size > 0
                  ? 'Type filters are active; clear them to change this'
                  : undefined
              }
              className={cn(
                'flex items-center rounded-lg border font-medium tracking-wide transition-all duration-200',
                compact
                  ? 'gap-1 px-2 py-1 text-[11px]'
                  : 'gap-1.5 px-2.5 py-1.5 text-xs',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-50',
                server.includeNoise
                  ? cn(
                      getEventConfig('child_session_update').bgColor,
                      getEventConfig('child_session_update').borderColor,
                      'text-teal-700 dark:text-teal-300',
                    )
                  : 'border-dashed border-slate-700/70 bg-slate-900/40 text-slate-500 hover:text-slate-300',
              )}
            >
              <GitFork className="h-3.5 w-3.5" aria-hidden />
              {server.includeNoise
                ? 'Showing sub-agent updates and usage counters'
                : 'Show sub-agent updates and usage counters'}
              {server.typeCounts !== null && (
                <span className="rounded bg-slate-800/60 px-1.5 py-0.5 font-mono text-[10px]">
                  {n(noiseCount)}
                </span>
              )}
            </button>
          )}

          {activeFilters.size > 0 && (
            <button
              type="button"
              onClick={clearFilters}
              className={cn(
                'flex items-center gap-1 rounded px-2 text-slate-500 transition-colors hover:text-slate-300',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400',
                compact ? 'py-1 text-[11px]' : 'py-1.5 text-xs',
              )}
            >
              <X className="w-3 h-3" aria-hidden />
              Clear filters
            </button>
          )}
        </div>
        {server && !countsFromServer && (
          <p className="text-[11px] text-slate-500">
            Session event counts are unavailable. Chip counts cover loaded
            events only.
          </p>
        )}
      </div>

      {/* Timeline */}
      <div
        ref={scrollRef}
        className={cn(
          'relative min-h-0 flex-1 overflow-y-auto',
          compact ? 'p-2' : 'p-4',
        )}
        aria-busy={server?.refreshing || server?.loadingMore || undefined}
      >
        {groupedByTurn.length === 0 ? (
          <TimelineEmpty
            server={server}
            filtering={filtering}
            noiseCount={noiseCount}
          />
        ) : virtualize ? (
          <div
            className="relative w-full"
            style={{ height: virtualizer.getTotalSize() }}
          >
            {virtualItems.map((item) => (
              <div
                key={item.key}
                data-index={item.index}
                ref={virtualizer.measureElement}
                className="absolute left-0 top-0 w-full"
                style={{ transform: `translateY(${item.start}px)` }}
              >
                {renderRow(rows[item.index])}
              </div>
            ))}
          </div>
        ) : (
          <div>
            {rows.map((row) => (
              <div key={row.key}>{renderRow(row)}</div>
            ))}
          </div>
        )}

        {server && groupedByTurn.length > 0 && (
          <div ref={loadMoreRef} className="flex justify-center py-4">
            {server.hasMore ? (
              <button
                type="button"
                onClick={server.onLoadMore}
                disabled={server.loadingMore}
                className="button-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-60"
              >
                {server.loadingMore && (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                )}
                {server.loadingMore
                  ? 'Loading more events...'
                  : server.loadMoreFailed
                    ? 'Loading failed. Retry loading more events'
                    : 'Load more events'}
              </button>
            ) : (
              <p className="text-xs text-slate-600">End of matching events</p>
            )}
          </div>
        )}
      </div>

      {/* Footer stats */}
      <div
        className={cn(
          'border-t border-slate-800/60 bg-slate-950/80 px-4 py-2',
          compact && !server && 'hidden',
        )}
      >
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs text-slate-500">
          <span role="status">
            {server ? (
              <ServerCoverage server={server} loaded={events.length} />
            ) : (
              `${visibleEvents.length} of ${events.length} events`
            )}
          </span>
          <span className="font-mono">
            {groupedByTurn.length} turn{groupedByTurn.length !== 1 ? 's' : ''}
            {server?.hasMore ? ' loaded' : ''}
          </span>
        </div>
      </div>
    </div>
  )
}

function ServerCoverage({
  server,
  loaded,
}: {
  server: TimelineServerState
  loaded: number
}) {
  const { matchingTotal, sessionTotal, hasMore } = server
  const partial = hasMore || (matchingTotal !== null && loaded < matchingTotal)
  const parts: string[] = []
  if (matchingTotal === null) {
    parts.push(`Showing ${n(loaded)} loaded events; matching total unavailable`)
  } else {
    parts.push(`Showing ${n(loaded)} of ${n(matchingTotal)} matching events`)
  }
  if (sessionTotal !== null && sessionTotal !== matchingTotal) {
    parts.push(`${n(sessionTotal)} in session`)
  }
  return (
    <>
      {parts.join(' · ')}
      {partial && (
        <span className="ml-2 rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-amber-700 dark:text-amber-200">
          Partial view
        </span>
      )}
      {server.refreshing && <span className="ml-2">Updating...</span>}
    </>
  )
}

function TimelineEmpty({
  server,
  filtering,
  noiseCount,
}: {
  server?: TimelineServerState
  filtering: boolean
  noiseCount: number
}) {
  if (server?.refreshing) {
    return (
      <p
        className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500"
        role="status"
      >
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        Loading events...
      </p>
    )
  }
  const onlyNoise =
    !!server && !filtering && !server.includeNoise && noiseCount > 0
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center text-slate-500">
      <Database className="w-12 h-12 mb-1 opacity-30" aria-hidden />
      <p className="text-sm">
        {filtering
          ? 'No events match the current search or filters'
          : onlyNoise
            ? 'This session only recorded sub-agent updates and usage counters'
            : server
              ? 'No events recorded for this session'
              : 'No events found'}
      </p>
      {filtering && !server && (
        <p className="text-xs text-slate-600">Try adjusting your filters</p>
      )}
      {filtering && server && (
        <button
          type="button"
          className="button-secondary mt-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          onClick={() => {
            server.onSearchChange('')
            server.onClearTypes()
          }}
        >
          Clear search and filters
        </button>
      )}
      {onlyNoise && server && (
        <button
          type="button"
          className="button-secondary mt-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
          onClick={server.onToggleNoise}
        >
          Show them
        </button>
      )}
    </div>
  )
}
