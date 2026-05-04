'use client'

import { ChevronDown, Download, Loader2, Tag, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import type { MemoryCategory } from '@/lib/memory-api'
import { CATEGORY_CONFIG } from '@/lib/memory-config'
import { cn } from '@/lib/utils'

export function BulkToolbar({
  selectedCount,
  selectedIds,
  onDelete,
  onExport,
  onClear,
  onTierChange,
  onBulkTag,
  isDeleting,
}: {
  selectedCount: number
  selectedIds: Set<string>
  onDelete: () => void
  onExport: () => void
  onClear: () => void
  onTierChange?: (ids: string[], tier: MemoryCategory) => Promise<void>
  onBulkTag?: (
    ids: string[],
    addTags: string[],
    removeTags: string[],
  ) => Promise<void>
  isDeleting: boolean
}) {
  const [tierDropdownOpen, setTierDropdownOpen] = useState(false)
  const [isChangingTier, setIsChangingTier] = useState(false)
  const [tagDropdownOpen, setTagDropdownOpen] = useState(false)
  const [tagInput, setTagInput] = useState('')
  const [isTagging, setIsTagging] = useState(false)

  if (selectedCount === 0) return null

  const handleTierChange = async (tier: MemoryCategory) => {
    if (!onTierChange) return
    setIsChangingTier(true)
    try {
      await onTierChange([...selectedIds], tier)
    } finally {
      setIsChangingTier(false)
      setTierDropdownOpen(false)
    }
  }

  return (
    <div
      className={cn(
        'fixed bottom-6 left-1/2 -translate-x-1/2 z-40',
        'flex items-center gap-3 px-4 py-3 rounded-xl',
        'bg-slate-800 shadow-2xl',
        'border border-slate-700',
        'animate-in slide-in-from-bottom-4 fade-in duration-200',
      )}
    >
      <span className="flex items-center gap-2 text-sm font-medium text-white">
        <span className="px-2 py-0.5 rounded-full bg-emerald-500 text-xs tabular-nums">
          {selectedCount}
        </span>
        selected
      </span>

      <div className="w-px h-6 bg-slate-600" />

      {onTierChange && (
        <div className="relative">
          <button
            onClick={() => setTierDropdownOpen(!tierDropdownOpen)}
            disabled={isDeleting || isChangingTier}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-700 hover:bg-slate-600 text-white disabled:opacity-50"
          >
            {isChangingTier ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <ChevronDown
                className={cn(
                  'w-4 h-4 transition-transform',
                  tierDropdownOpen && 'rotate-180',
                )}
              />
            )}
            Type
          </button>
          {tierDropdownOpen && (
            <div className="absolute bottom-full mb-2 left-0 w-44 rounded-lg border border-slate-700 bg-slate-900 shadow-xl overflow-hidden">
              {(['mandate', 'guardrail', 'reference'] as MemoryCategory[]).map(
                (tier) => {
                  const config = CATEGORY_CONFIG[tier]
                  return (
                    <button
                      key={tier}
                      onClick={() => handleTierChange(tier)}
                      disabled={isChangingTier}
                      className="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium hover:bg-slate-800 transition-colors disabled:opacity-50"
                    >
                      <span>{config.icon}</span>
                      <span className={config.color}>{config.label}</span>
                      <span className="text-[10px] text-slate-500 ml-auto">
                        {config.description}
                      </span>
                    </button>
                  )
                },
              )}
            </div>
          )}
        </div>
      )}

      {onBulkTag && (
        <div className="relative">
          <button
            onClick={() => {
              setTagDropdownOpen(!tagDropdownOpen)
              setTierDropdownOpen(false)
            }}
            disabled={isDeleting || isTagging}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-700 hover:bg-slate-600 text-white disabled:opacity-50"
          >
            {isTagging ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Tag className="w-4 h-4" />
            )}
            Tag
          </button>
          {tagDropdownOpen && (
            <div className="absolute bottom-full mb-2 left-0 w-52 rounded-lg border border-slate-700 bg-slate-900 shadow-xl overflow-hidden p-2">
              <input
                type="text"
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={async (e) => {
                  if (e.key === 'Enter' && tagInput.trim()) {
                    e.preventDefault()
                    setIsTagging(true)
                    await onBulkTag(
                      [...selectedIds],
                      [tagInput.trim().toLowerCase()],
                      [],
                    )
                    setIsTagging(false)
                    setTagInput('')
                    setTagDropdownOpen(false)
                  }
                }}
                placeholder="Type tag + Enter"
                className="w-full px-2 py-1.5 text-xs rounded border border-slate-700 bg-slate-800 text-slate-200 focus:outline-none focus:ring-1 focus:ring-emerald-500/40 mb-1.5"
              />
              <p className="text-[10px] text-slate-500 px-1">
                Enter to add tag to {selectedCount} episodes
              </p>
            </div>
          )}
        </div>
      )}

      <button
        onClick={onDelete}
        disabled={isDeleting}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium bg-red-600 hover:bg-red-700 text-white disabled:opacity-50"
      >
        {isDeleting ? (
          <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
        ) : (
          <Trash2 className="w-4 h-4" />
        )}
        Delete
      </button>

      <button
        onClick={onExport}
        disabled={isDeleting}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-700 hover:bg-slate-600 text-white disabled:opacity-50"
      >
        <Download className="w-4 h-4" />
        Export
      </button>

      <div className="w-px h-6 bg-slate-600" />

      <button
        onClick={onClear}
        disabled={isDeleting}
        className="p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-700 disabled:opacity-50"
        title="Clear selection"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}
