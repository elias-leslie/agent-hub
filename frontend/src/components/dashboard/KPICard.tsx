import { cn } from '@/lib/utils'

// ─────────────────────────────────────────────────────────────────────────────
// KPI CARD - Compact metrics display
// ─────────────────────────────────────────────────────────────────────────────

export function KPICard({
  label,
  value,
  subtext,
  icon: Icon,
  status = 'neutral',
  pulse = false,
}: {
  label: string
  value: string
  subtext?: string
  icon: React.ComponentType<{ className?: string }>
  status?: 'success' | 'warning' | 'error' | 'neutral'
  pulse?: boolean
}) {
  const statusConfig = {
    success: {
      border: 'border-l-emerald-500',
      glow: 'shadow-emerald-500/5',
      dot: 'bg-emerald-500',
    },
    warning: {
      border: 'border-l-amber-500',
      glow: 'shadow-amber-500/5',
      dot: 'bg-amber-500',
    },
    error: {
      border: 'border-l-red-500',
      glow: 'shadow-red-500/5',
      dot: 'bg-red-500',
    },
    neutral: {
      border: 'border-l-slate-600',
      glow: '',
      dot: 'bg-slate-400',
    },
  }

  const config = statusConfig[status]

  return (
    <div
      className={cn(
        'group relative min-h-[132px] overflow-hidden rounded-2xl border border-slate-800/80 bg-[linear-gradient(180deg,rgba(15,23,42,0.82),rgba(15,23,42,0.58))] backdrop-blur-sm transition-all duration-200',
        'hover:-translate-y-0.5 hover:shadow-[0_20px_46px_-34px_rgba(0,0,0,0.92)]',
        config.glow,
      )}
    >
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/14 to-transparent" />
      <div
        className={cn(
          'absolute left-5 right-5 top-0 h-0.5 rounded-full opacity-90',
          config.dot,
        )}
      />
      <div className="absolute -right-10 top-5 h-24 w-24 rounded-full bg-slate-800/60 blur-2xl" />

      <div className="relative p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="truncate text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                {label}
              </span>
              {pulse && (
                <span
                  className={cn(
                    'w-1.5 h-1.5 rounded-full animate-pulse shrink-0',
                    config.dot,
                  )}
                />
              )}
            </div>
            <p className="mt-3 text-[1.7rem] font-semibold tracking-tight text-slate-50 font-mono tabular-nums">
              {value}
            </p>
            {subtext && (
              <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
                {subtext}
              </p>
            )}
          </div>
          <div className="shrink-0 rounded-xl border border-slate-800/70 bg-slate-900/75 p-2 text-slate-300 transition-colors group-hover:border-slate-700/80 group-hover:bg-slate-800/80">
            <Icon className="h-4 w-4" />
          </div>
        </div>
      </div>
    </div>
  )
}
