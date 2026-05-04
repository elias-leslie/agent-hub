'use client'

import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import type { SessionTimelineEvent } from '@/lib/api'
import { cn } from '@/lib/utils'
import { EventItem } from './event-item'

interface TurnGroupProps {
  turn: number
  events: SessionTimelineEvent[]
  isLast: boolean
}

export function TurnGroup({ turn, events, isLast }: TurnGroupProps) {
  const [isCollapsed, setIsCollapsed] = useState(false)

  return (
    <div className="relative">
      {/* Turn header */}
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        className={cn(
          'sticky top-0 z-10 w-full flex items-center gap-3 py-2 px-3 mb-3',
          'bg-slate-950/95 backdrop-blur-sm',
          'border-b border-slate-800/60',
          'hover:bg-slate-900/80 transition-colors',
          'text-left',
        )}
      >
        <div className="flex items-center gap-2">
          {isCollapsed ? (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          )}
          <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">
            Turn {turn}
          </span>
        </div>
        <div className="flex-1 h-px bg-gradient-to-r from-slate-800 to-transparent" />
        <span className="text-xs text-slate-600 font-mono">
          {events.length} event{events.length !== 1 ? 's' : ''}
        </span>
      </button>

      {/* Events */}
      {!isCollapsed && (
        <div className="pl-2">
          {events.map((event, idx) => (
            <EventItem
              key={event.id}
              event={event}
              isFirst={idx === 0}
              isLast={idx === events.length - 1 && isLast}
            />
          ))}
        </div>
      )}
    </div>
  )
}
