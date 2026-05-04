'use client'

import type { MemoryCategory } from '@/lib/memory-api'
import { CATEGORY_CONFIG } from '@/lib/memory-config'
import { cn } from '@/lib/utils'
import { Tooltip } from './Tooltip'

const FALLBACK_CONFIG = {
  icon: '📝',
  label: 'Unknown',
  color: 'text-slate-400',
  bg: 'bg-slate-500/10 border-slate-400/40',
  description: '',
}

export function CategoryPill({
  category,
  onClick,
  isActive,
  size = 'sm',
}: {
  category: MemoryCategory | string
  onClick?: () => void
  isActive?: boolean
  size?: 'sm' | 'md'
}) {
  const config = CATEGORY_CONFIG[category as MemoryCategory] ?? FALLBACK_CONFIG

  const pill = (
    <span
      onClick={(e) => {
        if (onClick) {
          e.stopPropagation()
          onClick()
        }
      }}
      className={cn(
        'inline-flex items-center gap-1 rounded border font-semibold tracking-wide transition-all',
        size === 'sm' ? 'px-1.5 py-0.5 text-[9px]' : 'px-2 py-1 text-[10px]',
        onClick && 'cursor-pointer hover:scale-105 active:scale-95',
        isActive && 'ring-2 ring-offset-1 ring-offset-slate-900',
        config.color,
        config.bg,
        isActive && 'ring-current',
      )}
    >
      <span>{config.icon}</span>
      <span className="uppercase">{config.label}</span>
    </span>
  )

  if (!config.description) return pill

  return <Tooltip content={config.description}>{pill}</Tooltip>
}
