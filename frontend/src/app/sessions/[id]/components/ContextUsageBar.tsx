import { AlertCircle, Gauge } from 'lucide-react'
import type { ContextUsage } from '@/lib/api'
import { cn } from '@/lib/utils'
import { formatTokens } from './utils'

export function ContextUsageBar({ usage }: { usage: ContextUsage }) {
  const percent = Math.min(100, usage.percent_used)
  const isWarning = percent > 70
  const isDanger = percent > 90

  return (
    <div className={cn('section-card')}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Gauge className="h-4 w-4 text-slate-500" />
          <span className="text-sm font-medium text-slate-300">
            Context Usage
          </span>
        </div>
        <span className="text-sm font-mono text-slate-400">
          {formatTokens(usage.used_tokens)} / {formatTokens(usage.limit_tokens)}
        </span>
      </div>
      <div className="h-2 bg-slate-800/80 rounded-full overflow-hidden">
        <div
          className={cn(
            'h-full rounded-full transition-all duration-500',
            isDanger
              ? 'bg-gradient-to-r from-red-600 to-red-500'
              : isWarning
                ? 'bg-gradient-to-r from-amber-600 to-amber-500'
                : 'bg-gradient-to-r from-emerald-600 to-emerald-500',
          )}
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
        <span>{percent.toFixed(1)}% used</span>
        <span>{formatTokens(usage.remaining_tokens)} remaining</span>
      </div>
      {usage.warning && (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-amber-400">
          <AlertCircle className="h-3.5 w-3.5" />
          <span>{usage.warning}</span>
        </div>
      )}
    </div>
  )
}
