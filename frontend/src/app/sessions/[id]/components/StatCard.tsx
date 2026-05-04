import type { Activity } from 'lucide-react'
import { cn } from '@/lib/utils'

interface StatCardProps {
  icon: typeof Activity
  label: string
  value: string | number
  subValue?: string
}

export function StatCard({
  icon: Icon,
  label,
  value,
  subValue,
}: StatCardProps) {
  return (
    <div className={cn('detail-card')}>
      <div className="flex items-center gap-2 mb-1">
        <Icon className="h-3.5 w-3.5 text-slate-500" />
        <span className="detail-label tracking-[0.16em]">{label}</span>
      </div>
      <p className="mt-2 text-sm font-medium text-slate-200 truncate">
        {value}
      </p>
      {subValue && (
        <p className="mt-1 text-xs text-slate-500 truncate">{subValue}</p>
      )}
    </div>
  )
}
