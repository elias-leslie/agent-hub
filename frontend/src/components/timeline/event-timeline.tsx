'use client'

import { Database, Search, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { SessionTimelineEvent } from '@/lib/api'
import { cn } from '@/lib/utils'
import { EVENT_CONFIGS } from './event-config'
import { FilterChip } from './filter-chip'
import { TurnGroup } from './turn-group'

type EventType = SessionTimelineEvent['event_type']

interface EventTimelineProps {
  events: SessionTimelineEvent[]
  className?: string
  density?: 'default' | 'compact'
}

export function EventTimeline({
  events,
  className,
  density = 'default',
}: EventTimelineProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [activeFilters, setActiveFilters] = useState<Set<EventType>>(new Set())
  const compact = density === 'compact'

  // Count events by type
  const eventCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    events.forEach((e) => {
      counts[e.event_type] = (counts[e.event_type] || 0) + 1
    })
    return counts
  }, [events])

  // Filter events
  const filteredEvents = useMemo(() => {
    return events.filter((e) => {
      // Filter by type
      if (
        activeFilters.size > 0 &&
        !activeFilters.has(e.event_type as EventType)
      ) {
        return false
      }
      // Filter by search
      if (searchQuery) {
        const query = searchQuery.toLowerCase()
        return (
          e.content?.toLowerCase().includes(query) ||
          e.tool_name?.toLowerCase().includes(query) ||
          e.agent_name?.toLowerCase().includes(query) ||
          JSON.stringify(e.tool_input)?.toLowerCase().includes(query) ||
          JSON.stringify(e.tool_output)?.toLowerCase().includes(query)
        )
      }
      return true
    })
  }, [events, activeFilters, searchQuery])

  // Group by turn
  const groupedByTurn = useMemo(() => {
    const groups: Map<number, SessionTimelineEvent[]> = new Map()
    filteredEvents.forEach((event) => {
      const existing = groups.get(event.turn) || []
      existing.push(event)
      groups.set(event.turn, existing)
    })
    return Array.from(groups.entries()).sort((a, b) => a[0] - b[0])
  }, [filteredEvents])

  const toggleFilter = (eventType: EventType) => {
    setActiveFilters((prev) => {
      const next = new Set(prev)
      if (next.has(eventType)) {
        next.delete(eventType)
      } else {
        next.add(eventType)
      }
      return next
    })
  }

  const allEventTypes: EventType[] = [
    'user_message',
    'assistant_message',
    'thinking',
    'tool_use',
    'tool_result',
    'memory_inject',
    'memory_cite',
    'error',
  ]

  const presentEventTypes = allEventTypes.filter((t) => eventCounts[t] > 0)

  return (
    <div className={cn('flex flex-col h-full', className)}>
      {/* Filters header */}
      <div
        className={cn(
          'sticky top-0 z-20 border-b border-slate-800/60 bg-slate-950/95 backdrop-blur-sm',
          compact ? 'flex flex-wrap items-center gap-2 p-2' : 'space-y-3 p-4',
        )}
      >
        {/* Search */}
        <div className={cn('relative', compact && 'min-w-[220px] flex-1')}>
          <Search
            className={cn(
              'absolute left-3 top-1/2 -translate-y-1/2 text-slate-500',
              compact ? 'h-3 w-3' : 'h-4 w-4',
            )}
          />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search events..."
            className={cn(
              'w-full rounded-lg pl-9 pr-9',
              compact ? 'py-1.5 text-xs' : 'py-2 text-sm',
              'bg-slate-900/60 border border-slate-800/60',
              'text-slate-300 placeholder:text-slate-600',
              'focus:outline-none focus:ring-1 focus:ring-slate-700 focus:border-slate-700',
              'transition-all duration-200',
            )}
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-400"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Filter chips */}
        <div className={cn('flex flex-wrap', compact ? 'gap-1.5' : 'gap-2')}>
          {presentEventTypes.map((eventType) => (
            <FilterChip
              key={eventType}
              label={EVENT_CONFIGS[eventType]?.label || eventType}
              eventType={eventType}
              isActive={activeFilters.has(eventType)}
              count={eventCounts[eventType] || 0}
              compact={compact}
              onClick={() => toggleFilter(eventType)}
            />
          ))}

          {activeFilters.size > 0 && (
            <button
              onClick={() => setActiveFilters(new Set())}
              className={cn(
                'flex items-center gap-1 px-2 text-slate-500 transition-colors hover:text-slate-400',
                compact ? 'py-1 text-[11px]' : 'py-1.5 text-xs',
              )}
            >
              <X className="w-3 h-3" />
              Clear filters
            </button>
          )}
        </div>
      </div>

      {/* Timeline */}
      <div className={cn('flex-1 overflow-y-auto', compact ? 'p-2' : 'p-4')}>
        {groupedByTurn.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            <Database className="w-12 h-12 mb-3 opacity-30" />
            <p className="text-sm">No events found</p>
            {(searchQuery || activeFilters.size > 0) && (
              <p className="text-xs text-slate-600 mt-1">
                Try adjusting your filters
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            {groupedByTurn.map(([turn, turnEvents], idx) => (
              <TurnGroup
                key={turn}
                turn={turn}
                events={turnEvents}
                isLast={idx === groupedByTurn.length - 1}
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer stats */}
      <div
        className={cn(
          'border-t border-slate-800/60 bg-slate-950/80 px-4 py-2',
          compact && 'hidden',
        )}
      >
        <div className="flex items-center justify-between text-xs text-slate-600">
          <span>
            {filteredEvents.length} of {events.length} events
          </span>
          <span className="font-mono">
            {groupedByTurn.length} turn{groupedByTurn.length !== 1 ? 's' : ''}
          </span>
        </div>
      </div>
    </div>
  )
}
