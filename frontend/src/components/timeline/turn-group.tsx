'use client'

import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import type { SessionTimelineEvent } from '@/lib/api'
import type { NativeCommandEvidence } from '@/lib/api/native-evidence'
import { cn } from '@/lib/utils'
import { EventItem } from './event-item'

interface TurnHeaderProps {
  turn: number
  count: number
  collapsed: boolean
  onToggle: () => void
  /** Sticky only works when rows are in normal flow (not virtualized). */
  sticky?: boolean
  /** The turn may continue in events that are not loaded yet. */
  incomplete?: boolean
  className?: string
}

export function TurnHeader({
  turn,
  count,
  collapsed,
  onToggle,
  sticky = true,
  incomplete = false,
  className,
}: TurnHeaderProps) {
  return (
    <button
      type="button"
      aria-expanded={!collapsed}
      onClick={onToggle}
      className={cn(
        sticky && 'sticky top-0',
        'z-10 w-full flex items-center gap-3 py-2 px-3',
        'bg-slate-950/95 backdrop-blur-sm',
        'border-b border-slate-800/60',
        'hover:bg-slate-900/80 transition-colors',
        'text-left',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400',
        className,
      )}
    >
      <div className="flex items-center gap-2">
        {collapsed ? (
          <ChevronRight className="w-4 h-4 text-slate-500" aria-hidden />
        ) : (
          <ChevronDown className="w-4 h-4 text-slate-500" aria-hidden />
        )}
        <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">
          Turn {turn}
        </span>
      </div>
      <div className="flex-1 h-px bg-gradient-to-r from-slate-800 to-transparent" />
      <span className="text-xs text-slate-600 font-mono">
        {count} event{count !== 1 ? 's' : ''}
        {incomplete ? ' loaded so far' : ''}
      </span>
    </button>
  )
}

interface TurnGroupProps {
  turn: number
  events: SessionTimelineEvent[]
  isLast: boolean
  commandByEvent?: Map<string, NativeCommandEvidence[]>
}

export function TurnGroup({
  turn,
  events,
  isLast,
  commandByEvent,
}: TurnGroupProps) {
  const [isCollapsed, setIsCollapsed] = useState(false)

  return (
    <div className="relative">
      <TurnHeader
        turn={turn}
        count={events.length}
        collapsed={isCollapsed}
        onToggle={() => setIsCollapsed(!isCollapsed)}
        className="mb-3"
      />

      {!isCollapsed && (
        <div className="pl-2">
          {events.map((event, idx) => (
            <EventItem
              key={event.id}
              event={event}
              nativeCommands={commandByEvent?.get(event.id)}
              isFirst={idx === 0}
              isLast={idx === events.length - 1 && isLast}
            />
          ))}
        </div>
      )}
    </div>
  )
}
