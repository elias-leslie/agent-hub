import {
  CheckCircle2,
  Download,
  Quote,
  ThumbsDown,
  ThumbsUp,
  Zap,
} from 'lucide-react'
import type { UsageTotals } from '@/lib/memory-api'
import { cn } from '@/lib/utils'

interface UsageStatsProps {
  data: UsageTotals
}

export function UsageStats({ data }: UsageStatsProps) {
  const items = [
    {
      label: 'Loaded',
      value: data.loaded,
      icon: Download,
      color: 'text-sky-400',
      bg: 'bg-sky-500/10',
    },
    {
      label: 'Cited',
      value: data.cited,
      icon: Quote,
      color: 'text-emerald-400',
      bg: 'bg-emerald-500/10',
    },
    {
      label: 'Success',
      value: data.success ?? 0,
      icon: CheckCircle2,
      color: 'text-green-400',
      bg: 'bg-green-500/10',
    },
    {
      label: 'Helpful',
      value: data.helpful,
      icon: ThumbsUp,
      color: 'text-teal-400',
      bg: 'bg-teal-500/10',
    },
    {
      label: 'Harmful',
      value: data.harmful,
      icon: ThumbsDown,
      color: 'text-amber-400',
      bg: 'bg-amber-500/10',
    },
    {
      label: 'Tracked Events',
      value: data.loaded + data.cited + (data.success ?? 0),
      icon: Zap,
      color: 'text-violet-400',
      bg: 'bg-violet-500/10',
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-3">
      {items.map((item) => (
        <div
          key={item.label}
          className="flex items-center gap-3 p-4 rounded-lg bg-slate-900/60 border border-slate-800/80 hover:shadow-lg hover:shadow-black/20 transition-all duration-200"
        >
          <div className={cn('p-2 rounded-md', item.bg)}>
            <item.icon className={cn('h-4 w-4', item.color)} />
          </div>
          <div>
            <p className="text-xl font-semibold text-slate-50 font-mono tabular-nums">
              {item.value.toLocaleString()}
            </p>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
              {item.label}
            </p>
          </div>
        </div>
      ))}
    </div>
  )
}
