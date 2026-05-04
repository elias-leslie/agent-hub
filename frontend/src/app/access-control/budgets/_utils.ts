// ─── Alert level config ───────────────────────────────────────────────────────

import { AlertCircle, AlertTriangle } from 'lucide-react'

export const ALERT_CONFIG = {
  warning: {
    label: 'Warning',
    icon: AlertTriangle,
    textColor: 'text-amber-400',
    bgColor: 'bg-amber-500/10',
    borderColor: 'border-amber-500/30',
  },
  critical: {
    label: 'Critical',
    icon: AlertCircle,
    textColor: 'text-red-400',
    bgColor: 'bg-red-500/10',
    borderColor: 'border-red-500/30',
  },
} as const

// ─── Progress bar color helpers ───────────────────────────────────────────────

export function getProgressColor(used: number, limit: number | null): string {
  if (limit === null || limit === 0) return 'bg-slate-600'
  const pct = used / limit
  if (pct >= 0.9) return 'bg-red-500'
  if (pct >= 0.7) return 'bg-amber-500'
  return 'bg-emerald-500'
}

export function getProgressBgColor(used: number, limit: number | null): string {
  if (limit === null || limit === 0) return 'bg-slate-800'
  const pct = used / limit
  if (pct >= 0.9) return 'bg-red-500/10'
  if (pct >= 0.7) return 'bg-amber-500/10'
  return 'bg-emerald-500/10'
}

export function getProgressPercent(used: number, limit: number | null): number {
  if (limit === null || limit === 0) return 0
  return Math.min((used / limit) * 100, 100)
}
