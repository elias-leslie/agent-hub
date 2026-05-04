import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import { cn } from '@/lib/utils'

export type SortDirection = 'asc' | 'desc'

export function SortableHeader<T extends string>({
  label,
  field,
  currentField,
  direction,
  onSort,
  icon,
  align = 'left',
}: {
  label: string
  field: T
  currentField: T
  direction: SortDirection
  onSort: (field: T) => void
  icon?: React.ReactNode
  align?: 'left' | 'right'
}) {
  const isActive = currentField === field

  return (
    <button
      onClick={() => onSort(field)}
      className={cn(
        'flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider transition-colors',
        'text-slate-500 hover:text-slate-300',
        isActive && 'text-slate-200',
        align === 'right' && 'justify-end ml-auto',
      )}
    >
      {icon}
      {label}
      {isActive ? (
        direction === 'asc' ? (
          <ArrowUp className="h-3 w-3" />
        ) : (
          <ArrowDown className="h-3 w-3" />
        )
      ) : (
        <ArrowUpDown className="h-3 w-3 opacity-30" />
      )}
    </button>
  )
}
