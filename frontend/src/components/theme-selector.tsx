'use client'

import { LaptopMinimal, MoonStar, SunMedium } from 'lucide-react'
import type { ThemePreference } from '@/lib/theme'
import { cn } from '@/lib/utils'
import { useTheme } from './theme-provider'

const THEME_OPTIONS: Array<{
  value: ThemePreference
  label: string
  icon: React.ComponentType<{ className?: string }>
}> = [
  { value: 'system', label: 'System', icon: LaptopMinimal },
  { value: 'light', label: 'Light', icon: SunMedium },
  { value: 'dark', label: 'Dark', icon: MoonStar },
]

interface ThemeSelectorProps {
  className?: string
  compact?: boolean
}

export function ThemeSelector({
  className,
  compact = false,
}: ThemeSelectorProps) {
  const { theme, resolvedTheme, setTheme } = useTheme()

  return (
    <div className={cn('space-y-3', className)}>
      <div
        role="group"
        aria-label="Theme preference"
        className={cn(
          'segmented-control w-full',
          compact && 'w-auto rounded-xl p-1',
        )}
      >
        {THEME_OPTIONS.map((option) => {
          const Icon = option.icon
          const active = theme === option.value
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={active}
              onClick={() => setTheme(option.value)}
              className={cn(
                'segmented-option justify-center',
                active
                  ? 'border-amber-400/20 bg-amber-500/12 text-amber-300 shadow-[0_18px_36px_-28px_rgba(245,158,11,0.55)]'
                  : 'hover:border-slate-700/70 hover:bg-slate-900/70 hover:text-slate-100',
                compact && 'px-3 py-2 text-xs',
              )}
            >
              <Icon className="h-4 w-4" />
              <span>{option.label}</span>
            </button>
          )
        })}
      </div>
      {!compact && (
        <p className="text-xs text-slate-500">
          Current appearance:{' '}
          <span className="font-medium text-slate-300">
            {resolvedTheme === 'dark' ? 'Dark' : 'Light'}
          </span>
          . Preference is saved locally and respects your system setting by
          default.
        </p>
      )}
    </div>
  )
}
