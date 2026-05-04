'use client'

import { Check, ChevronDown } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/utils'
import { TIER_CONFIG, TIERS, type Tier } from './tier-config'

export function TierSelect({
  value,
  onChange,
  disabled,
}: {
  value: Tier
  onChange: (tier: Tier) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 })
  const config = TIER_CONFIG[value]
  const Icon = config.icon

  const updatePosition = useCallback(() => {
    if (!buttonRef.current) return
    const rect = buttonRef.current.getBoundingClientRect()
    setMenuPos({ top: rect.bottom + 4, left: rect.left })
  }, [])

  useEffect(() => {
    if (!open) return
    updatePosition()
    window.addEventListener('scroll', () => setOpen(false), { passive: true })
    return () => window.removeEventListener('scroll', () => setOpen(false))
  }, [open, updatePosition])

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => !disabled && setOpen(!open)}
        disabled={disabled}
        className={cn(
          'flex items-center gap-2 px-3 py-1.5 rounded-md',
          'border border-slate-700/80 bg-slate-800/60',
          'hover:bg-slate-800 hover:border-slate-600',
          'transition-colors text-sm',
          'focus:outline-none focus:ring-1 focus:ring-amber-500/50',
          disabled && 'opacity-50 cursor-not-allowed',
        )}
      >
        <span className={cn('h-2 w-2 rounded-full', config.dot)} />
        <Icon className={cn('h-3.5 w-3.5', config.color)} />
        <span className={cn('font-medium', config.color)}>{config.label}</span>
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 text-slate-500 transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>

      {open &&
        createPortal(
          <>
            <div
              className="fixed inset-0 z-30"
              onClick={() => setOpen(false)}
              onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
            />
            <div
              className="fixed z-40 w-56 rounded-lg border border-slate-700 bg-slate-900 shadow-xl shadow-black/40 overflow-hidden"
              style={{ top: menuPos.top, left: menuPos.left }}
            >
              {TIERS.map((tier) => {
                const tc = TIER_CONFIG[tier]
                const TIcon = tc.icon
                const selected = tier === value
                return (
                  <button
                    key={tier}
                    type="button"
                    onClick={() => {
                      onChange(tier)
                      setOpen(false)
                    }}
                    className={cn(
                      'w-full flex items-center gap-3 px-3 py-2.5 text-left',
                      'hover:bg-slate-800/80 transition-colors',
                      selected && 'bg-slate-800/50',
                    )}
                  >
                    <span
                      className={cn(
                        'h-2 w-2 rounded-full flex-shrink-0',
                        tc.dot,
                      )}
                    />
                    <TIcon className={cn('h-4 w-4 flex-shrink-0', tc.color)} />
                    <div className="flex-1 min-w-0">
                      <p className={cn('text-sm font-medium', tc.color)}>
                        {tc.label}
                      </p>
                      <p className="text-[11px] text-slate-500">
                        {tc.description}
                      </p>
                    </div>
                    {selected && (
                      <Check className="h-4 w-4 text-amber-400 flex-shrink-0" />
                    )}
                  </button>
                )
              })}
            </div>
          </>,
          document.body,
        )}
    </div>
  )
}
