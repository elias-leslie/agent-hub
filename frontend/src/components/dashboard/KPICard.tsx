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
        'group relative min-h-[132px] overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/65 backdrop-blur-sm transition-all duration-200',
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
        <div className="flex min-w-0 items-center gap-1.5 text-slate-400 transition-colors group-hover:text-slate-300">
          <Icon className="h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 break-words text-[10px] font-semibold uppercase leading-tight tracking-[0.14em] text-slate-500">
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
    </div>
  )
}
