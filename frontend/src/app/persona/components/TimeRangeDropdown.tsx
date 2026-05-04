'use client'

import { ChevronDown, Clock } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

const TIME_RANGES = [
  { value: '6h', label: '6h' },
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
  { value: 'all', label: 'All' },
] as const

export type TimeRange = (typeof TIME_RANGES)[number]['value']

interface TimeRangeDropdownProps {
  value: TimeRange
  onChange: (value: TimeRange) => void
}

export function TimeRangeDropdown({ value, onChange }: TimeRangeDropdownProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const activeLabel = TIME_RANGES.find((r) => r.value === value)?.label ?? value

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          'flex items-center gap-1.5 px-2.5 py-2 rounded-lg text-xs font-medium transition-all',
          'border border-slate-700/50',
          'bg-slate-900/60 hover:bg-slate-800/60 hover:border-slate-600/50',
          'text-slate-400',
        )}
      >
        <Clock className="w-3 h-3 text-slate-500" />
        <span className="font-mono tabular-nums">{activeLabel}</span>
        <ChevronDown
          className={cn(
            'w-3 h-3 text-slate-600 transition-transform duration-200',
            open && 'rotate-180',
          )}
        />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 z-50 min-w-[7rem] rounded-xl border border-slate-700/50 bg-slate-800/95 backdrop-blur-lg shadow-xl shadow-black/40 py-1.5">
          {TIME_RANGES.map((range) => (
            <button
              key={range.value}
              onClick={() => {
                onChange(range.value)
                setOpen(false)
              }}
              className={cn(
                'w-full px-3.5 py-2 text-left text-xs font-mono transition-colors',
                range.value === value
                  ? 'bg-amber-500/10 text-amber-300 font-semibold'
                  : 'text-slate-300 hover:bg-slate-700/40',
              )}
            >
              {range.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
