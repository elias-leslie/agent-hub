'use client'

import { cn } from '@/lib/utils'
import { formatHour } from './tier-config'

export function HourSelect({
  value,
  onChange,
  disabled,
}: {
  value: number
  onChange: (v: number) => void
  disabled?: boolean
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      disabled={disabled}
      className={cn(
        'bg-slate-800/60 border border-slate-700/80 rounded-md',
        'px-2 py-1 text-xs text-slate-300 font-mono',
        'focus:outline-none focus:ring-1 focus:ring-amber-500/50 focus:border-amber-500/50',
        'hover:border-slate-600 transition-colors',
        disabled && 'opacity-40 cursor-not-allowed',
      )}
    >
      {Array.from({ length: 25 }, (_, i) => (
        <option key={i} value={i}>
          {formatHour(i)}
        </option>
      ))}
    </select>
  )
}
