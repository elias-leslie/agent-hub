'use client'

import { useState } from 'react'
import type { MemoryCategory, MemoryEpisode } from '@/lib/memory-api'
import { EditEpisodeModal } from './EditEpisodeModal'
import { MetadataPane } from './MetadataPane'
import { ScopePill } from './ScopePill'
import { SimilarEpisodesList } from './SimilarEpisodesList'
import { TierDropdown } from './TierDropdown'
import { TriggerTaskTypes } from './TriggerTaskTypes'
import { UsageStatsPane } from './UsageStatsPane'

export function ExpandedRowContent({
  episode,
  onDelete,
  isDeleting,
  onTierChange,
  onEdit,
}: {
  episode: MemoryEpisode
  onDelete: () => void
  isDeleting: boolean
  onTierChange?: (newCategory: MemoryCategory) => void
  onEdit?: () => void
}) {
  const [isEditModalOpen, setIsEditModalOpen] = useState(false)

  return (
    <div className="px-5 py-4 space-y-3">
      {/* TOP BAR: pills + meta + actions */}
      <div className="flex items-start justify-between gap-4">
        {/* Left: scope, tier, source pills */}
        <div className="flex items-center gap-2 flex-wrap">
          <ScopePill scope={episode.scope} size="md" />
          <TierDropdown
            episodeUuid={episode.uuid}
            currentCategory={episode.category}
            onTierChange={onTierChange}
          />
          {episode.context_kind && (
            <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-cyan-950/40 text-cyan-300 uppercase">
              {episode.context_kind}
            </span>
          )}
          <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-slate-800 text-slate-400 uppercase">
            {episode.source}
          </span>
        </div>

        {/* Right: metadata + actions */}
        <MetadataPane
          episode={episode}
          onEdit={() => setIsEditModalOpen(true)}
          onDelete={onDelete}
          isDeleting={isDeleting}
        />
      </div>

      {/* CONTENT */}
      <div className="p-3 rounded-lg bg-slate-800/40 border border-slate-700/50">
        <p className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">
          {episode.content}
        </p>
      </div>

      {/* BOTTOM: triggers + stats + similar */}
      <div className="space-y-2.5">
        {/* Trigger Task Types - only for reference tier */}
        {episode.category === 'reference' && (
          <TriggerTaskTypes
            episodeUuid={episode.uuid}
            initialTriggerTypes={episode.trigger_task_types || []}
          />
        )}

        {/* Stats bar + Similar button */}
        <div className="flex items-center justify-between gap-3 pt-1 border-t border-slate-800/50">
          <UsageStatsPane
            loadedCount={episode.loaded_count}
            referencedCount={episode.referenced_count}
            helpfulCount={episode.helpful_count}
            harmfulCount={episode.harmful_count}
            utilityScore={episode.utility_score}
            lifecycleScore={episode.lifecycle_score}
          />
          <SimilarEpisodesList episodeUuid={episode.uuid} />
        </div>
      </div>

      {/* Edit Modal */}
      <EditEpisodeModal
        episode={episode}
        isOpen={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        onSaved={() => onEdit?.()}
      />
    </div>
  )
}
