import { BarChart3 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { COLOR_MAP, type ColorVariant } from './analytics-constants'

export const TIME_RANGES = [
  { label: '1h', value: '1h' },
  { label: '1d', value: '1d' },
  { label: '7d', value: '7d' },
  { label: '14d', value: '14d' },
  { label: '30d', value: '30d' },
] as const

export type AnalyticsLookback = (typeof TIME_RANGES)[number]['value']

interface TimeRangeSelectorProps {
  value: AnalyticsLookback
  onChange: (lookback: AnalyticsLookback) => void
}

export function TimeRangeSelector({ value, onChange }: TimeRangeSelectorProps) {
  return (
    <div className="flex items-center gap-1 bg-slate-800/60 rounded-lg p-1">
      {TIME_RANGES.map((range) => (
        <button
          key={range.value}
          onClick={() => onChange(range.value)}
          className={cn(
            'px-3 py-1 text-xs font-medium rounded-md transition-all duration-150',
            value === range.value
              ? 'bg-purple-600 text-white shadow-sm'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50',
          )}
        >
          {range.label}
        </button>
      ))}
    </div>
  )
}

type StatusDotVariant = 'active' | 'warning' | 'inactive'

interface StatusDotProps {
  status: StatusDotVariant
}

export function StatusDot({ status }: StatusDotProps) {
  return (
    <span className="relative flex h-2.5 w-2.5">
      {status === 'active' && (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
      )}
      <span
        className={cn(
          'relative inline-flex h-2.5 w-2.5 rounded-full',
          status === 'active' && 'bg-green-500',
          status === 'warning' && 'bg-amber-500',
          status === 'inactive' && 'bg-slate-500',
        )}
      />
    </span>
  )
}

interface MetricCardProps {
  label: string
  value: string
  icon: React.ComponentType<{ className?: string }>
  color?: ColorVariant
}

export function MetricCard({
  label,
  value,
  icon: Icon,
  color = 'emerald',
}: MetricCardProps) {
  const c = COLOR_MAP[color]

  return (
    <div
      className={cn(
        'bg-slate-900/60 border border-slate-800/80 border-l-[3px] rounded-lg p-4',
        c.border,
        'hover:shadow-lg hover:shadow-black/20 transition-all duration-200',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
            {label}
          </span>
          <p className="mt-1.5 text-2xl font-semibold tracking-tight text-slate-50 font-mono tabular-nums">
            {value}
          </p>
        </div>
        <div className={cn('p-2 rounded-md', c.iconBg)}>
          <Icon className={cn('h-4 w-4', c.iconText)} />
        </div>
      </div>
    </div>
  )
}

interface SectionHeaderProps {
  title: string
  icon: React.ComponentType<{ className?: string }>
}

export function SectionHeader({ title, icon: Icon }: SectionHeaderProps) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className="h-4 w-4 text-purple-400" />
      <h3 className="text-sm font-semibold text-slate-200 uppercase tracking-wide">
        {title}
      </h3>
    </div>
  )
}

export function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-32 text-sm text-slate-500">
      {label}
    </div>
  )
}

export function SkeletonCard() {
  return (
    <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-4 animate-pulse">
      <div className="h-3 w-20 bg-slate-700 rounded mb-3" />
      <div className="h-7 w-16 bg-slate-700 rounded" />
    </div>
  )
}

export function SkeletonSection() {
  return (
    <div className="bg-slate-900/60 border border-slate-800/80 rounded-lg p-5 animate-pulse">
      <div className="h-3 w-32 bg-slate-700 rounded mb-4" />
      <div className="space-y-3">
        <div className="h-6 w-full bg-slate-800 rounded" />
        <div className="h-6 w-3/4 bg-slate-800 rounded" />
        <div className="h-6 w-1/2 bg-slate-800 rounded" />
      </div>
    </div>
  )
}

export function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="p-4 rounded-full bg-slate-800 mb-4">
        <BarChart3 className="w-8 h-8 text-slate-400" />
      </div>
      <h3 className="text-lg font-medium text-slate-100 mb-1">
        No Analytics Data
      </h3>
      <p className="text-sm text-slate-400 max-w-sm">
        Analytics will appear once episodes are created and used in memory
        injection.
      </p>
    </div>
  )
}
