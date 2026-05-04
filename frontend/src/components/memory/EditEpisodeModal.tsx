'use client'

import { Loader2, Pencil, X } from 'lucide-react'
import type { MemoryEpisode } from '@/lib/memory-api'
import { cn } from '@/lib/utils'
import { EpisodeFormFields } from './EpisodeFormFields'
import { TierSelector } from './TierSelector'
import { useEpisodeEditor } from './useEpisodeEditor'

interface EditEpisodeModalProps {
  episode: MemoryEpisode
  isOpen: boolean
  onClose: () => void
  onSaved: () => void
}

export function EditEpisodeModal({
  episode,
  isOpen,
  onClose,
  onSaved,
}: EditEpisodeModalProps) {
  const {
    content,
    setContent,
    tier,
    setTier,
    pinned,
    setPinned,
    summary,
    setSummary,
    contextKind,
    setContextKind,
    applicability,
    setApplicability,
    triggerPhases,
    setTriggerPhases,
    isSaving,
    error,
    hasChanges,
    handleSave,
  } = useEpisodeEditor({ episode, onSaved, onClose })

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      data-testid="edit-episode-modal"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-full max-w-3xl mx-4 rounded-xl bg-slate-900 shadow-2xl border border-slate-800">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-full bg-violet-900/30">
              <Pencil className="w-5 h-5 text-violet-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-100">
                Edit Memory
              </h2>
              <p className="text-xs text-slate-400 font-mono">
                {episode.uuid.slice(0, 8)}...
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isSaving}
            aria-label="Close dialog"
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 disabled:opacity-50 cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          <TierSelector value={tier} onChange={setTier} disabled={isSaving} />

          <EpisodeFormFields
            summary={summary}
            onSummaryChange={setSummary}
            pinned={pinned}
            onPinnedChange={setPinned}
            content={content}
            onContentChange={setContent}
            contextKind={contextKind}
            onContextKindChange={setContextKind}
            applicability={applicability}
            onApplicabilityChange={setApplicability}
            triggerPhases={triggerPhases}
            onTriggerPhasesChange={setTriggerPhases}
            episodeUuid={episode.uuid}
            disabled={isSaving}
          />

          {/* Error Message */}
          {error && (
            <div className="p-3 rounded-lg bg-red-900/20 border border-red-800">
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          {/* Info Box */}
          <div className="p-3 rounded-lg bg-amber-900/20 border border-amber-800">
            <p className="text-xs text-amber-400">
              <strong>Note:</strong> Editing creates a new memory with the
              updated content while preserving usage statistics (helpful/harmful
              counts, load count, etc.).
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-4 border-t border-slate-800 bg-slate-800/30">
          <div className="text-xs text-slate-500">
            {hasChanges ? (
              <span className="text-violet-400">Unsaved changes</span>
            ) : (
              'No changes'
            )}
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              disabled={isSaving}
              className="px-4 py-2 rounded-lg text-sm font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={isSaving || !hasChanges || !content.trim()}
              className={cn(
                'px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors flex items-center gap-2',
                'bg-violet-600 hover:bg-violet-700',
                'disabled:opacity-50 disabled:cursor-not-allowed',
              )}
            >
              {isSaving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Saving...
                </>
              ) : (
                'Save Changes'
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
