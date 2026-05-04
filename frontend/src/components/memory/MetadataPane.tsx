'use client'

import { Pencil, Trash2 } from 'lucide-react'
import type { MemoryEpisode } from '@/lib/memory-api'
import { cn } from '@/lib/utils'
import { CopyButton } from './CopyButton'
import { Tooltip } from './Tooltip'

interface MetadataPaneProps {
  episode: MemoryEpisode
  onEdit: () => void
  onDelete: () => void
  isDeleting: boolean
}

export function MetadataPane({
  episode,
  onEdit,
  onDelete,
  isDeleting,
}: MetadataPaneProps) {
  return (
    <div className="flex flex-col gap-3">
      {/* Metadata row */}
      <div className="flex items-center gap-3 text-[11px] text-slate-500">
        <div className="flex items-center gap-1">
          <code className="font-mono text-slate-400">
            {episode.uuid.slice(0, 8)}
          </code>
          <CopyButton text={episode.uuid} />
        </div>
        <span className="text-slate-600">|</span>
        <span className="font-mono tabular-nums">
          {new Date(episode.created_at).toLocaleDateString()}
        </span>
        {episode.scope_id && (
          <>
            <span className="text-slate-600">|</span>
            <code className="font-mono truncate max-w-[120px]">
              {episode.scope_id}
            </code>
          </>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-1.5">
        <Tooltip content="Edit episode">
          <button
            onClick={(e) => {
              e.stopPropagation()
              onEdit()
            }}
            className={cn(
              'p-1.5 rounded-md transition-colors',
              'text-slate-500 hover:text-violet-400 hover:bg-violet-900/20',
            )}
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
        </Tooltip>
        <Tooltip content="Delete episode">
          <button
            onClick={(e) => {
              e.stopPropagation()
              onDelete()
            }}
            disabled={isDeleting}
            className={cn(
              'p-1.5 rounded-md transition-colors',
              'text-slate-500 hover:text-red-400 hover:bg-red-900/20',
              'disabled:opacity-50 disabled:cursor-not-allowed',
            )}
          >
            {isDeleting ? (
              <div className="w-3.5 h-3.5 border-2 border-red-500 border-t-transparent rounded-full animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
          </button>
        </Tooltip>
      </div>
    </div>
  )
}
