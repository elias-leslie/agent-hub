import { EventStream, LiveBadge } from '@/components/monitoring'
import type { SessionEvent } from '@/types/events'

interface LiveEventsPanelProps {
  events: SessionEvent[]
}

export function LiveEventsPanel({ events }: LiveEventsPanelProps) {
  return (
    <div className="mb-5 rounded-lg border border-green-800 bg-slate-900 overflow-hidden">
      <div className="px-4 py-2 bg-green-950/30 border-b border-green-800 flex items-center gap-2">
        <LiveBadge size="sm" />
        <span className="text-xs font-semibold text-green-300">
          Real-time Events
        </span>
        <span className="text-[10px] text-green-400 ml-auto font-mono tabular-nums">
          {events.length}
        </span>
      </div>
      <EventStream events={events} maxHeight="200px" />
    </div>
  )
}
