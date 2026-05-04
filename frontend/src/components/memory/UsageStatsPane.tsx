'use client'

import {
  Activity,
  Eye,
  MessageCircle,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Tooltip } from './Tooltip'

interface UsageStatsPaneProps {
  loadedCount?: number
  referencedCount?: number
  helpfulCount?: number
  harmfulCount?: number
  utilityScore?: number
  lifecycleScore?: number
}

interface StatItemProps {
  icon: React.ReactNode
  label: string
  value: number
  color?: string
  tooltip?: string
}

function StatItem({ icon, label, value, color, tooltip }: StatItemProps) {
  const content = (
    <div
      className={cn(
        'flex items-center gap-1.5 px-2 py-1 rounded-md border transition-colors',
        color || 'border-slate-700/50 text-slate-400',
      )}
    >
      {icon}
      <span className="text-[10px] font-medium tabular-nums">{value}</span>
      <span className="text-[9px] uppercase tracking-wide opacity-60 hidden sm:inline">
        {label}
      </span>
    </div>
  )

  return tooltip ? <Tooltip content={tooltip}>{content}</Tooltip> : content
}

export function UsageStatsPane({
  loadedCount,
  referencedCount,
  helpfulCount,
  harmfulCount,
  utilityScore,
  lifecycleScore,
}: UsageStatsPaneProps) {
  const hasStats =
    loadedCount !== undefined ||
    referencedCount !== undefined ||
    helpfulCount !== undefined ||
    harmfulCount !== undefined

  if (!hasStats) return null

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {loadedCount !== undefined && (
        <StatItem
          icon={<Eye className="h-3 w-3" />}
          label="loaded"
          value={loadedCount}
          tooltip="Times injected into context"
        />
      )}
      {referencedCount !== undefined && (
        <StatItem
          icon={<MessageCircle className="h-3 w-3" />}
          label="cited"
          value={referencedCount}
          tooltip="Times cited by agent"
        />
      )}
      {helpfulCount !== undefined && helpfulCount > 0 && (
        <StatItem
          icon={<ThumbsUp className="h-3 w-3" />}
          label="helpful"
          value={helpfulCount}
          color="border-emerald-800/50 text-emerald-400"
          tooltip="Marked helpful"
        />
      )}
      {harmfulCount !== undefined && harmfulCount > 0 && (
        <StatItem
          icon={<ThumbsDown className="h-3 w-3" />}
          label="harmful"
          value={harmfulCount}
          color="border-red-800/50 text-red-400"
          tooltip="Marked harmful"
        />
      )}
      {utilityScore !== undefined && (
        <StatItem
          icon={<Sparkles className="h-3 w-3" />}
          label="utility"
          value={Math.round(utilityScore * 100)}
          color={cn(
            utilityScore >= 0.7
              ? 'border-emerald-800/50 text-emerald-400'
              : utilityScore >= 0.4
                ? 'border-amber-800/50 text-amber-400'
                : 'border-slate-700/50 text-slate-400',
          )}
          tooltip={`Utility score: referenced / (loaded + 1) = ${(utilityScore * 100).toFixed(0)}%`}
        />
      )}
      {lifecycleScore !== undefined && (
        <StatItem
          icon={<Activity className="h-3 w-3" />}
          label="lifecycle"
          value={Math.round(lifecycleScore * 100)}
          color={cn(
            lifecycleScore >= 0.7
              ? 'border-emerald-800/50 text-emerald-400'
              : lifecycleScore >= 0.4
                ? 'border-amber-800/50 text-amber-400'
                : 'border-slate-700/50 text-slate-400',
          )}
          tooltip={`Lifecycle score (continuous health metric) = ${(lifecycleScore * 100).toFixed(0)}%`}
        />
      )}
    </div>
  )
}
