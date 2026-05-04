import type { SessionTimelineEvent } from '@/lib/api'
import { cn } from '@/lib/utils'
import { getEventConfig } from './event-config'

type EventType = SessionTimelineEvent['event_type']

interface FilterChipProps {
  label: string
  eventType: EventType
  isActive: boolean
  count: number
  compact?: boolean
  onClick: () => void
}

export function FilterChip({
  label,
  eventType,
  isActive,
  count,
  compact = false,
  onClick,
}: FilterChipProps) {
  const config = getEventConfig(eventType)
  const Icon = config.icon

  return (
    <button
      onClick={onClick}
      className={cn(
        'flex items-center rounded-lg',
        compact ? 'gap-1 px-2 py-1' : 'gap-1.5 px-2.5 py-1.5',
        compact
          ? 'text-[11px] font-medium tracking-wide'
          : 'text-xs font-medium tracking-wide',
        'border transition-all duration-200',
        isActive
          ? cn(config.bgColor, config.borderColor, config.color)
          : 'bg-slate-900/40 border-slate-800/50 text-slate-500 hover:text-slate-400 hover:border-slate-700',
      )}
    >
      <Icon className={compact ? 'h-3 w-3' : 'h-3.5 w-3.5'} />
      <span>{label}</span>
      <span
        className={cn(
          'rounded font-mono',
          compact ? 'px-1 py-0 text-[10px]' : 'px-1.5 py-0.5 text-[10px]',
          isActive ? 'bg-slate-400/10' : 'bg-slate-800/60',
        )}
      >
        {count}
      </span>
    </button>
  )
}
