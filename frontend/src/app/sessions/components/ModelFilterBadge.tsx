import { X } from 'lucide-react'

interface ModelFilterBadgeProps {
  modelFilter: string
  onClear: () => void
}

export function ModelFilterBadge({
  modelFilter,
  onClear,
}: ModelFilterBadgeProps) {
  if (!modelFilter) return null

  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/30 bg-amber-950/20 px-2.5 py-1 text-[11px] font-medium text-amber-200">
      {modelFilter}
      <button
        type="button"
        aria-label="Clear model filter"
        onClick={onClear}
        className="rounded-full p-0.5 transition hover:bg-amber-500/10"
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  )
}
