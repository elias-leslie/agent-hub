import type { LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ToggleSettingProps {
  label: string
  enabled: boolean
  onToggle: () => void
  activeIcon: LucideIcon
  inactiveIcon: LucideIcon
  activeLabel: string
  inactiveLabel: string
  activeDescription: string
  inactiveDescription: string
  variant?: 'default' | 'danger' | 'sky' | 'violet'
}

export function ToggleSetting({
  label,
  enabled,
  onToggle,
  activeIcon: ActiveIcon,
  inactiveIcon: InactiveIcon,
  activeLabel,
  inactiveLabel,
  activeDescription,
  inactiveDescription,
  variant = 'default',
}: ToggleSettingProps) {
  const getVariantStyles = () => {
    switch (variant) {
      case 'danger':
        return enabled
          ? 'border-slate-700 hover:bg-slate-800/50'
          : 'border-red-900 bg-red-900/20'
      case 'sky':
        return 'border-sky-700 hover:bg-sky-900/20'
      case 'violet':
        return 'border-violet-700 hover:bg-violet-900/20'
      default:
        return 'border-slate-700 hover:bg-slate-800/50'
    }
  }

  const Icon = enabled ? ActiveIcon : InactiveIcon

  return (
    <div className="space-y-2">
      <label className="text-sm font-medium text-slate-300">{label}</label>
      <button
        onClick={onToggle}
        className={cn(
          'flex items-center gap-3 w-full p-3 rounded-lg border transition-colors',
          getVariantStyles(),
        )}
      >
        <Icon
          className={cn(
            variant === 'danger' ? 'w-6 h-6' : 'w-8 h-8',
            enabled
              ? variant === 'danger'
                ? 'text-green-500'
                : variant === 'sky'
                  ? 'text-sky-500'
                  : variant === 'violet'
                    ? 'text-violet-500'
                    : 'text-green-500'
              : variant === 'danger'
                ? 'text-red-500'
                : variant === 'sky'
                  ? 'text-slate-400'
                  : variant === 'violet'
                    ? 'text-slate-400'
                    : 'text-amber-500',
          )}
        />
        <div className="text-left">
          <div className="font-medium text-slate-100">
            {enabled ? activeLabel : inactiveLabel}
          </div>
          <div className="text-xs text-slate-500">
            {enabled ? activeDescription : inactiveDescription}
          </div>
        </div>
      </button>
    </div>
  )
}
