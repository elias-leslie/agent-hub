import type { MemoryAnalyticsState } from '@/lib/memory-api'
import { cn } from '@/lib/utils'
import { EmptyChart } from '../analytics-components'

interface ScopeChartProps {
  data: MemoryAnalyticsState['scope_distribution']
}

export function ScopeChart({ data }: ScopeChartProps) {
  if (data.length === 0) return <EmptyChart label="No scope data" />

  return (
    <div className="space-y-3">
      {data.map((d) => (
        <div key={d.scope}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm text-slate-300 capitalize">{d.scope}</span>
            <span className="text-sm font-mono text-slate-400">
              {d.count} ({d.percentage}%)
            </span>
          </div>
          <div className="h-3 rounded-full bg-slate-800 overflow-hidden">
            <div
              className={cn(
                'h-full rounded-full transition-all duration-500',
                d.scope === 'global' ? 'bg-indigo-500' : 'bg-teal-500',
              )}
              style={{ width: `${d.percentage}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}
