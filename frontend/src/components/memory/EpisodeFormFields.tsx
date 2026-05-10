'use client'

import { FileText, Pin } from 'lucide-react'
import { CompactnessMeter } from '@/components/CompactnessMeter'
import type { RenderMode } from '@/lib/memory-api'
import { cn } from '@/lib/utils'

interface EpisodeFormFieldsProps {
  summary: string
  onSummaryChange: (value: string) => void
  pinned: boolean
  onPinnedChange: (value: boolean) => void
  content: string
  onContentChange: (value: string) => void
  renderMode: RenderMode | null
  onRenderModeChange: (value: RenderMode | null) => void
  episodeUuid: string
  disabled?: boolean
}

const RENDER_MODE_OPTIONS: Array<{
  value: '' | RenderMode
  label: string
  description: string
}> = [
  {
    value: '',
    label: 'Auto (profile decides)',
    description: 'Uses the consumer profile’s default tier rules.',
  },
  {
    value: 'full',
    label: 'Full text (L2)',
    description: 'Always inject the full content of this memory.',
  },
  {
    value: 'compact',
    label: 'Compact (L1)',
    description: 'Inject the compact ~220-character overview.',
  },
  {
    value: 'summary',
    label: 'One-line summary (L0)',
    description: 'Inject only the ~72-character summary.',
  },
]

export function EpisodeFormFields({
  summary,
  onSummaryChange,
  pinned,
  onPinnedChange,
  content,
  onContentChange,
  renderMode,
  onRenderModeChange,
  episodeUuid,
  disabled,
}: EpisodeFormFieldsProps) {
  return (
    <>
      {/* Summary Field */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300 flex items-center gap-2">
          <FileText className="w-4 h-4 text-cyan-500" />
          Summary
          <span className="text-xs font-normal text-slate-400">
            (for TOON index)
          </span>
        </label>
        <input
          type="text"
          value={summary}
          onChange={(e) => onSummaryChange(e.target.value)}
          disabled={disabled}
          maxLength={40}
          className={cn(
            'w-full px-3 py-2.5 rounded-lg text-sm font-mono',
            'bg-slate-800/50',
            'border border-slate-700',
            'text-slate-100',
            'placeholder:text-slate-400',
            'focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500',
            'disabled:opacity-50 disabled:cursor-not-allowed',
          )}
          placeholder="e.g., use st check"
        />
        <p className="text-xs text-slate-400">
          Short action phrase (~20 chars) shown in reference index:{' '}
          <code className="text-cyan-400">
            {episodeUuid.slice(0, 8)}:{summary || '...'}
          </code>
        </p>
      </div>

      {/* Pinned Toggle */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">
          Always Show
        </label>
        <button
          type="button"
          onClick={() => onPinnedChange(!pinned)}
          disabled={disabled}
          className={cn(
            'flex items-center gap-3 w-full px-3 py-2.5 rounded-lg border text-sm transition-all',
            pinned ? 'border-violet-700 bg-violet-900/20' : 'border-slate-700',
            'hover:ring-2 hover:ring-offset-1 hover:ring-slate-600',
            'disabled:opacity-50 disabled:cursor-not-allowed',
          )}
        >
          <Pin
            className={cn(
              'w-4 h-4',
              pinned ? 'text-violet-400' : 'text-slate-400',
            )}
          />
          <span
            className={
              pinned ? 'text-violet-300 font-medium' : 'text-slate-400'
            }
          >
            {pinned ? 'Pinned (always shown)' : 'Not pinned'}
          </span>
        </button>
        <p className="text-xs text-slate-400">
          Pinned episodes are always included when memory and this category are
          enabled, regardless of budget limits.
        </p>
      </div>

      {/* Render Mode */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">
          Render Mode
        </label>
        <select
          value={renderMode ?? ''}
          onChange={(e) => {
            const value = e.target.value
            onRenderModeChange(value === '' ? null : (value as RenderMode))
          }}
          disabled={disabled}
          className={cn(
            'w-full px-3 py-2.5 rounded-lg text-sm',
            'bg-slate-800/50 border border-slate-700 text-slate-100',
            'focus:outline-none focus:ring-2 focus:ring-amber-500/40 focus:border-amber-500',
            'disabled:opacity-50 disabled:cursor-not-allowed',
          )}
        >
          {RENDER_MODE_OPTIONS.map((option) => (
            <option key={option.value || 'auto'} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <p className="text-xs text-slate-400">
          {RENDER_MODE_OPTIONS.find(
            (option) => option.value === (renderMode ?? ''),
          )?.description ??
            'Override the auto-tiering for this memory across all profiles.'}
        </p>
      </div>

      {/* Content Editor */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">Content</label>
        <textarea
          value={content}
          onChange={(e) => onContentChange(e.target.value)}
          disabled={disabled}
          rows={8}
          className={cn(
            'w-full px-3 py-2.5 rounded-lg text-sm',
            'bg-slate-800/50',
            'border border-slate-700',
            'text-slate-100',
            'placeholder:text-slate-400',
            'focus:outline-none focus:ring-2 focus:ring-violet-500/50 focus:border-violet-500',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            'resize-none',
          )}
          placeholder="Enter memory content..."
        />
        <p className="text-xs text-slate-400">{content.length} characters</p>
        <CompactnessMeter content={content} kind="memory" />
      </div>
    </>
  )
}
