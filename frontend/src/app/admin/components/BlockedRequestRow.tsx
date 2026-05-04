import { ChevronDown, Clock } from 'lucide-react'
import type { BlockedRequest } from '@/lib/api'
import { cn } from '@/lib/utils'
import { formatRelativeTime } from '../utils'
import { ExpandedRowContent } from './ExpandedRowContent'
import { TABLE_GRID_COLS } from './tableConfig'

interface BlockedRequestRowProps {
  request: BlockedRequest
  index: number
  isFocused: boolean
  isExpanded: boolean
  onToggleExpand: (index: number) => void
}

export function BlockedRequestRow({
  request,
  index,
  isFocused,
  isExpanded,
  onToggleExpand,
}: BlockedRequestRowProps) {
  return (
    <div className={cn(isExpanded && 'bg-slate-800/30')}>
      {/* Row */}
      <button
        onClick={() => onToggleExpand(index)}
        className={cn(
          'w-full grid gap-3 px-4 py-3 items-center text-left transition-colors',
          TABLE_GRID_COLS,
          'hover:bg-slate-800/30',
          isFocused && 'bg-amber-950/20 ring-1 ring-inset ring-amber-800',
          isExpanded && 'bg-amber-950/10',
        )}
      >
        {/* Time */}
        <div className="flex items-center gap-2">
          <Clock className="w-3 h-3 text-slate-600" />
          <span className="text-xs font-mono tabular-nums text-slate-400">
            {formatRelativeTime(request.timestamp)}
          </span>
        </div>

        {/* Client */}
        <div>
          <span
            className={cn(
              'text-xs font-medium px-2 py-0.5 rounded',
              request.client_name === '<unknown>'
                ? 'bg-red-900/40 text-red-400 border border-red-700/50 animate-pulse'
                : request.client_name
                  ? 'bg-amber-900/30 text-amber-400 border border-amber-700/50'
                  : 'text-slate-600',
            )}
          >
            {request.client_name === '<unknown>'
              ? 'UNKNOWN'
              : request.client_name || '—'}
          </span>
        </div>

        {/* Endpoint */}
        <div className="min-w-0">
          <code className="text-xs font-mono text-slate-300 truncate block">
            {request.endpoint}
          </code>
        </div>

        {/* Reason */}
        <div className="min-w-0">
          <span className="text-xs text-red-400 truncate block">
            {request.block_reason}
          </span>
        </div>

        {/* Expand indicator */}
        <div className="flex items-center justify-end">
          <ChevronDown
            className={cn(
              'h-4 w-4 text-slate-600 transition-transform duration-200',
              isExpanded && 'rotate-180 text-amber-400',
            )}
          />
        </div>
      </button>

      {/* Expanded Content */}
      <div
        className={cn(
          'grid transition-all duration-300 ease-out',
          isExpanded
            ? 'grid-rows-[1fr] opacity-100'
            : 'grid-rows-[0fr] opacity-0',
        )}
      >
        <div className="overflow-hidden">
          <div className="border-t border-slate-800 bg-slate-900/50">
            <ExpandedRowContent request={request} />
          </div>
        </div>
      </div>
    </div>
  )
}
