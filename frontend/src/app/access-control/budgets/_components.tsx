'use client'

import { AlertCircle, Check } from 'lucide-react'
import { formatCurrency } from '@/lib/formatters'
import { cn } from '@/lib/utils'
import {
  ALERT_CONFIG,
  getProgressBgColor,
  getProgressColor,
  getProgressPercent,
} from './_utils'

// ─── Alert level badge ────────────────────────────────────────────────────────

export function AlertBadge({
  level,
}: {
  level: 'warning' | 'critical' | null
}) {
  if (!level) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium bg-slate-500/10 text-slate-500">
        None
      </span>
    )
  }

  const config = ALERT_CONFIG[level]
  const Icon = config.icon

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium border',
        config.bgColor,
        config.textColor,
        config.borderColor,
      )}
    >
      <Icon className="h-3 w-3" />
      {config.label}
    </span>
  )
}

// ─── Budget progress bar ──────────────────────────────────────────────────────

export function BudgetBar({
  used,
  limit,
}: {
  used: number
  limit: number | null
}) {
  const percent = getProgressPercent(used, limit)
  const barColor = getProgressColor(used, limit)
  const bgColor = getProgressBgColor(used, limit)

  if (limit === null) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-sm font-mono text-slate-300">
          {formatCurrency(used)}
        </span>
        <span className="text-[11px] text-slate-600">/ no limit</span>
      </div>
    )
  }

  return (
    <div className="min-w-[160px]">
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-sm font-mono text-slate-300">
          {formatCurrency(used)}
        </span>
        <span className="text-[11px] text-slate-500">
          / {formatCurrency(limit)}
        </span>
      </div>
      <div className={cn('h-1.5 rounded-full overflow-hidden', bgColor)}>
        <div
          className={cn(
            'h-full rounded-full transition-all duration-500',
            barColor,
          )}
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="mt-0.5 text-right">
        <span className="text-[10px] text-slate-600">
          {percent.toFixed(0)}%
        </span>
      </div>
    </div>
  )
}

// ─── Save flash indicator ─────────────────────────────────────────────────────

export function SaveFlash({
  saving,
  error,
}: {
  saving: boolean
  error: boolean
}) {
  if (!saving && !error) return null
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium',
        'animate-pulse',
        error
          ? 'bg-red-900/30 text-red-400'
          : 'bg-emerald-900/30 text-emerald-400',
      )}
    >
      {error ? (
        <>
          <AlertCircle className="h-3 w-3" /> Error
        </>
      ) : (
        <>
          <Check className="h-3 w-3" /> Saved
        </>
      )}
    </span>
  )
}

// ─── Overview stat card ───────────────────────────────────────────────────────

const STATUS_BORDER = {
  success: 'border-l-emerald-500',
  warning: 'border-l-amber-500',
  error: 'border-l-red-500',
  neutral: 'border-l-slate-600',
} as const

export function OverviewCard({
  label,
  value,
  subtext,
  icon: Icon,
  status = 'neutral',
}: {
  label: string
  value: string
  subtext?: string
  icon: React.ComponentType<{ className?: string }>
  status?: 'success' | 'warning' | 'error' | 'neutral'
}) {
  return (
    <div
      className={cn(
        'relative overflow-hidden',
        'bg-slate-900/60 backdrop-blur-sm',
        'border border-slate-800/80',
        'border-l-[3px]',
        STATUS_BORDER[status],
        'rounded-lg',
        'p-5',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
              {label}
            </span>
          </div>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-50 font-mono tabular-nums">
            {value}
          </p>
          {subtext && <p className="mt-1 text-xs text-slate-400">{subtext}</p>}
        </div>
        <div className="p-2 rounded-md bg-slate-800/80">
          <Icon className="h-5 w-5 text-slate-400" />
        </div>
      </div>
    </div>
  )
}
