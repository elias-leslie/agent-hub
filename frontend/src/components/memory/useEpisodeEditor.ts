import { useState } from 'react'
import type {
  MemoryCategory,
  MemoryEpisode,
  RenderMode,
} from '@/lib/memory-api'
import {
  addEpisode,
  deleteMemory,
  updateEpisodeProperties,
} from '@/lib/memory-api'

interface UseEpisodeEditorProps {
  episode: MemoryEpisode
  onSaved: () => void
  onClose: () => void
}

interface SaveOptions {
  bypassCompactness?: boolean
}

export function useEpisodeEditor({
  episode,
  onSaved,
  onClose,
}: UseEpisodeEditorProps) {
  const [content, setContent] = useState(episode.content)
  const [tier, setTier] = useState<MemoryCategory>(episode.category)
  const [pinned, setPinned] = useState(episode.pinned ?? false)
  const [summary, setSummary] = useState(episode.summary ?? '')
  const [renderMode, setRenderMode] = useState<RenderMode | null>(
    episode.render_mode ?? null,
  )
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [canBypass, setCanBypass] = useState(false)

  const initialRenderMode = episode.render_mode ?? null

  const hasChanges =
    content !== episode.content ||
    tier !== episode.category ||
    pinned !== (episode.pinned ?? false) ||
    summary !== (episode.summary ?? '') ||
    renderMode !== initialRenderMode

  async function handleSave(options: SaveOptions = {}) {
    if (!hasChanges) {
      onClose()
      return
    }

    setIsSaving(true)
    setError(null)
    setCanBypass(false)

    try {
      const contentOrTierChanged =
        content !== episode.content || tier !== episode.category
      const pinnedChanged = pinned !== (episode.pinned ?? false)
      const summaryChanged = summary !== (episode.summary ?? '')

      let newUuid = episode.uuid

      if (contentOrTierChanged) {
        const newEpisode = await addEpisode({
          content,
          source: episode.source,
          source_description: episode.source_description,
          injection_tier: tier,
          preserve_stats_from: episode.uuid,
          bypass_compactness: options.bypassCompactness,
        })
        newUuid = newEpisode.uuid

        await deleteMemory(episode.uuid)
      }

      const propsToUpdate: {
        pinned?: boolean
        summary?: string
        render_mode?: RenderMode | null
      } = {}
      if (pinnedChanged || (contentOrTierChanged && pinned)) {
        propsToUpdate.pinned = pinned
      }
      if (summaryChanged || (contentOrTierChanged && summary)) {
        propsToUpdate.summary = summary
      }
      if (
        renderMode !== initialRenderMode ||
        (contentOrTierChanged && renderMode !== null)
      ) {
        propsToUpdate.render_mode = renderMode
      }
      if (Object.keys(propsToUpdate).length > 0) {
        await updateEpisodeProperties(newUuid, propsToUpdate)
      }

      onSaved()
      onClose()
    } catch (err) {
      const message =
        err instanceof Error ? err.message : 'Failed to save changes'
      setError(message)
      // The strict-Caveman gate is the only error path the UI can override.
      // Detect it by message; bypass shouldn't appear for header/atomic/etc.
      if (/strict Caveman gate/i.test(message)) {
        setCanBypass(true)
      }
    } finally {
      setIsSaving(false)
    }
  }

  return {
    content,
    setContent,
    tier,
    setTier,
    pinned,
    setPinned,
    summary,
    setSummary,
    renderMode,
    setRenderMode,
    isSaving,
    error,
    canBypass,
    hasChanges,
    handleSave,
  }
}
