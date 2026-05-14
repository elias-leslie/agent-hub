import { Server } from 'lucide-react'
import type { ProviderStatus } from '@/lib/api'
import { formatLatency } from '@/lib/formatters'
import { cn } from '@/lib/utils'

// ─────────────────────────────────────────────────────────────────────────────
// PROVIDER STATUS - Compact inline display
// ─────────────────────────────────────────────────────────────────────────────

export function ProviderStatusCard({ provider }: { provider: ProviderStatus }) {
  const health = provider.health
  const state =
    health?.state || (provider.available ? 'healthy' : 'unavailable')

  const stateConfig = {
    healthy: {
      color: 'text-emerald-500',
      bg: 'bg-emerald-500/10',
      label: 'Healthy',
      dot: 'bg-emerald-500',
    },
    degraded: {
      color: 'text-amber-500',
      bg: 'bg-amber-500/10',
      label: 'Degraded',
      dot: 'bg-amber-500',
    },
    unavailable: {
      color: 'text-red-500',
      bg: 'bg-red-500/10',
      label: 'Down',
      dot: 'bg-red-500',
    },
    unknown: {
      color: 'text-slate-400',
      bg: 'bg-slate-400/10',
      label: 'Unknown',
      dot: 'bg-slate-400',
    },
  }

  const config = stateConfig[state] || stateConfig.unknown

  return (
    <div className="flex items-center justify-between rounded-2xl border border-slate-800/70 bg-slate-900/75 p-3.5 transition-colors hover:border-slate-700/80 hover:bg-slate-900/95">
      <div className="flex items-center gap-3">
        <div
          className={cn('rounded-xl border border-slate-800/70 p-2', config.bg)}
        >
          <Server className="h-4 w-4 text-amber-400" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-100 capitalize">
              {provider.name}
            </span>
            <span
              className={cn(
                'w-1.5 h-1.5 rounded-full',
                config.dot,
                state === 'healthy' && 'animate-pulse',
              )}
            />
          </div>
          {health && (
            <div className="mt-1 flex items-center gap-2 text-[10px] font-mono text-slate-500">
              <span>{formatLatency(health.latency_ms)}</span>
              <span className="text-slate-700">|</span>
              <span>{(health.availability * 100).toFixed(0)}% avail</span>
            </div>
          )}
        </div>
      </div>
      <span
        className={cn(
          'rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]',
          config.bg,
          config.color,
        )}
      >
        {config.label}
      </span>
    </div>
  )
}
