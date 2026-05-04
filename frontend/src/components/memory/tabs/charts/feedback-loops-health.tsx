import type { MemoryAnalyticsActivity } from '@/lib/memory-api'
import { StatusDot } from '../analytics-components'

interface FeedbackLoopsHealthProps {
  activity: MemoryAnalyticsActivity
}

function getLoopStatus(value: number): 'active' | 'warning' | 'inactive' {
  if (value > 0) return 'active'
  return 'inactive'
}

export function FeedbackLoopsHealth({ activity }: FeedbackLoopsHealthProps) {
  const loops = [
    {
      name: 'Citation Scanning',
      description: 'Recent citations credited from session analysis',
      stat: `${activity.usage_totals.cited} cited`,
      status: getLoopStatus(activity.usage_totals.cited),
    },
    {
      name: 'Task Outcome',
      description: 'Recent tasks with known outcomes in the selected window',
      stat: `${activity.injection_metrics.outcomes.known_count} known`,
      status: getLoopStatus(activity.injection_metrics.outcomes.known_count),
    },
    {
      name: 'Helpful Signals',
      description: 'Recent helpful credits captured for cited memories',
      stat: `${activity.usage_totals.helpful} helpful`,
      status: getLoopStatus(activity.usage_totals.helpful),
    },
  ]

  return (
    <div className="space-y-3">
      {loops.map((loop) => (
        <div
          key={loop.name}
          className="flex items-center gap-3 p-3 rounded-lg bg-slate-800/40 border border-slate-800/60"
        >
          <StatusDot status={loop.status} />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-200">{loop.name}</p>
            <p className="text-[10px] text-slate-500 truncate">
              {loop.description}
            </p>
          </div>
          <span className="text-xs font-mono text-slate-400 shrink-0">
            {loop.stat}
          </span>
        </div>
      ))}
      <div className="pt-1 text-[10px] text-slate-500 text-center">
        {activity.injection_metrics.outcomes.unknown_count} injections still
        missing outcomes
      </div>
    </div>
  )
}
