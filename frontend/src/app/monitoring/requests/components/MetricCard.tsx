import { TrendingUp } from 'lucide-react'
import { cn } from '@/lib/utils'

export function MetricCard({
  label,
  value,
  subtext,
  icon: Icon,
  trend,
  status = 'neutral',
}: {
  label: string
  value: string
  subtext?: string
  icon: React.ComponentType<{ className?: string }>
  trend?: 'up' | 'down' | 'flat'
  status?: 'success' | 'warning' | 'error' | 'neutral'
}) {
  const statusColors = {
    success: 'border-l-emerald-500 shadow-emerald-500/5',
    warning: 'border-l-amber-500 shadow-amber-500/5',
    error: 'border-l-red-500 shadow-red-500/5',
    neutral: 'border-l-slate-600',
  }

  return (
    <div
      className={cn(
        'relative min-h-[132px] overflow-hidden rounded-2xl border border-slate-800/80 bg-[linear-gradient(180deg,rgba(15,23,42,0.82),rgba(15,23,42,0.58))] p-4 backdrop-blur-sm',
        'border-l-[3px] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_20px_46px_-34px_rgba(0,0,0,0.92)]',
        statusColors[status],
        'group',
      )}
    >
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/14 to-transparent" />
      <div className="absolute -top-8 -right-8 h-20 w-20 rounded-full bg-slate-800/60 blur-2xl" />

      <div className="relative flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
              {label}
            </span>
            {trend && (
              <TrendingUp
                className={cn(
                  'h-3 w-3',
                  trend === 'up' && 'text-emerald-500',
                  trend === 'down' && 'text-red-500 rotate-180',
                  trend === 'flat' && 'text-slate-500 rotate-90',
                )}
              />
            )}
          </div>
          <p className="mt-3 text-[1.7rem] font-semibold tracking-tight text-slate-50 font-mono tabular-nums">
            {value}
          </p>
          {subtext && <p className="mt-2 text-xs text-slate-400">{subtext}</p>}
        </div>
        <div className="rounded-xl border border-slate-800/70 bg-slate-900/75 p-2 transition-colors group-hover:border-slate-700/80 group-hover:bg-slate-800/80">
          <Icon className="h-4 w-4 text-slate-400" />
        </div>
      </div>
    </div>
  )
}
