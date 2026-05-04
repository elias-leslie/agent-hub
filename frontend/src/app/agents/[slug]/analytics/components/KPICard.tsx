import { TrendingDown, TrendingUp } from 'lucide-react'
import { cn } from '@/lib/utils'

interface KPICardProps {
  label: string
  value: string | number
  unit?: string
  icon: React.ElementType
  trend?: number
  color?: 'blue' | 'green' | 'amber' | 'red'
}

export function KPICard({
  label,
  value,
  unit,
  icon: Icon,
  trend,
  color = 'blue',
}: KPICardProps) {
  const colorClasses = {
    blue: 'bg-blue-950/30 text-blue-400',
    green: 'bg-emerald-950/30 text-emerald-400',
    amber: 'bg-amber-950/30 text-amber-400',
    red: 'bg-red-950/30 text-red-400',
  }

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">
            {label}
          </p>
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-bold text-slate-100 tabular-nums">
              {value}
            </span>
            {unit && <span className="text-sm text-slate-400">{unit}</span>}
          </div>
          {trend !== undefined && (
            <div
              className={cn(
                'flex items-center gap-1 mt-1 text-xs font-medium',
                trend >= 0 ? 'text-red-500' : 'text-emerald-500',
              )}
            >
              {trend >= 0 ? (
                <TrendingUp className="h-3 w-3" />
              ) : (
                <TrendingDown className="h-3 w-3" />
              )}
              {Math.abs(trend).toFixed(1)}% vs last 7d
            </div>
          )}
        </div>
        <div className={cn('p-2.5 rounded-lg', colorClasses[color])}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  )
}
