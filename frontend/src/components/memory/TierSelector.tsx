'use client'

import { Check, ChevronDown } from 'lucide-react'
import { useState } from 'react'
import type { MemoryCategory } from '@/lib/memory-api'
import { CATEGORY_CONFIG } from '@/lib/memory-config'
import { cn } from '@/lib/utils'

interface TierSelectorProps {
  value: MemoryCategory
  onChange: (tier: MemoryCategory) => void
  disabled?: boolean
}

const TIER_DESCRIPTIONS: Record<MemoryCategory, string> = {
  mandate: 'Always injected',
  guardrail: 'Always injected',
  reference: 'On-demand',
  archive: 'Cold storage',
}

export function TierSelector({ value, onChange, disabled }: TierSelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const tierConfig = CATEGORY_CONFIG[value]

  return (
    <div className="space-y-2">
      <label className="text-sm font-medium text-slate-300">Type</label>
      <div className="relative">
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          disabled={disabled}
          className={cn(
            'flex items-center gap-2 w-full px-3 py-2.5 rounded-lg border text-sm font-medium transition-all',
            tierConfig.bg,
            'border-slate-700',
            'hover:ring-2 hover:ring-offset-1 hover:ring-slate-600',
            'disabled:opacity-50 disabled:cursor-not-allowed',
          )}
        >
          <span className="text-base">{tierConfig.icon}</span>
          <span className={tierConfig.color}>{tierConfig.label}</span>
          <ChevronDown
            className={cn(
              'w-4 h-4 ml-auto text-slate-400 transition-transform',
              isOpen && 'rotate-180',
            )}
          />
        </button>

        {isOpen && (
          <div
            className="absolute top-full left-0 right-0 mt-1 z-50 rounded-lg border border-slate-700 bg-slate-900 shadow-lg overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {(
              [
                'mandate',
                'guardrail',
                'reference',
                'archive',
              ] as MemoryCategory[]
            ).map((t) => {
              const config = CATEGORY_CONFIG[t]
              const isSelected = t === value
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => {
                    onChange(t)
                    setIsOpen(false)
                  }}
                  className={cn(
                    'w-full flex items-center gap-3 px-3 py-2.5 text-sm font-medium transition-colors',
                    'hover:bg-slate-800',
                    isSelected && 'bg-slate-800',
                  )}
                >
                  <span className="text-base">{config.icon}</span>
                  <span className={config.color}>{config.label}</span>
                  <span className="text-xs text-slate-400 ml-1">
                    {TIER_DESCRIPTIONS[t]}
                  </span>
                  {isSelected && (
                    <Check className="w-4 h-4 ml-auto text-emerald-500" />
                  )}
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
