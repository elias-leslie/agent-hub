'use client'

import { Check, ChevronDown, Loader2 } from 'lucide-react'
import { useState } from 'react'
import type { MemoryCategory } from '@/lib/memory-api'
import { updateEpisodeTier } from '@/lib/memory-api'
import { CATEGORY_CONFIG } from '@/lib/memory-config'
import { cn } from '@/lib/utils'

interface TierDropdownProps {
  episodeUuid: string
  currentCategory: MemoryCategory
  onTierChange?: (newCategory: MemoryCategory) => void
}

export function TierDropdown({
  episodeUuid,
  currentCategory,
  onTierChange,
}: TierDropdownProps) {
  const [isDropdownOpen, setIsDropdownOpen] = useState(false)
  const [isUpdatingTier, setIsUpdatingTier] = useState(false)
  const [tierError, setTierError] = useState<string | null>(null)
  const categoryConfig = CATEGORY_CONFIG[currentCategory]

  const handleTierChange = async (newTier: MemoryCategory) => {
    if (newTier === currentCategory) {
      setIsDropdownOpen(false)
      return
    }

    setIsUpdatingTier(true)
    setTierError(null)
    try {
      await updateEpisodeTier(episodeUuid, newTier)
      onTierChange?.(newTier)
      setIsDropdownOpen(false)
    } catch (err) {
      setTierError(err instanceof Error ? err.message : 'Failed to update tier')
    } finally {
      setIsUpdatingTier(false)
    }
  }

  return (
    <div>
      <div className="relative">
        <button
          onClick={(e) => {
            e.stopPropagation()
            setIsDropdownOpen(!isDropdownOpen)
          }}
          disabled={isUpdatingTier}
          className={cn(
            'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition-all',
            categoryConfig.bg,
            categoryConfig.color,
            'hover:ring-2 hover:ring-offset-1 hover:ring-slate-600',
            'disabled:opacity-50 disabled:cursor-not-allowed',
          )}
        >
          <span>{categoryConfig.icon}</span>
          <span>{categoryConfig.label}</span>
          {isUpdatingTier ? (
            <Loader2 className="w-3 h-3 animate-spin ml-0.5" />
          ) : (
            <ChevronDown
              className={cn(
                'w-3 h-3 transition-transform',
                isDropdownOpen && 'rotate-180',
              )}
            />
          )}
        </button>

        {/* Dropdown Menu */}
        {isDropdownOpen && (
          <div
            className="absolute top-full left-0 mt-1 z-50 w-40 rounded-lg border border-slate-700 bg-slate-900 shadow-lg overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {(
              [
                'mandate',
                'guardrail',
                'reference',
                'archive',
              ] as MemoryCategory[]
            ).map((tier) => {
              const config = CATEGORY_CONFIG[tier]
              const isSelected = tier === currentCategory
              return (
                <button
                  key={tier}
                  onClick={() => handleTierChange(tier)}
                  disabled={isUpdatingTier}
                  className={cn(
                    'w-full flex items-center gap-2 px-3 py-2 text-xs font-medium transition-colors',
                    'hover:bg-slate-800',
                    isSelected && 'bg-slate-800',
                  )}
                >
                  <span>{config.icon}</span>
                  <span className={config.color}>{config.label}</span>
                  {isSelected && (
                    <Check className="w-3 h-3 ml-auto text-emerald-500" />
                  )}
                </button>
              )
            })}
          </div>
        )}
      </div>

      {/* Tier Error Message */}
      {tierError && (
        <div className="text-xs text-red-400 mt-1">{tierError}</div>
      )}
    </div>
  )
}
