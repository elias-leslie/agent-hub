import { useState } from 'react'
import type {
  MemoryApplicability,
  MemoryCategory,
  MemoryContextKind,
  MemoryEpisode,
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

export function useEpisodeEditor({
  episode,
  onSaved,
  onClose,
}: UseEpisodeEditorProps) {
  const defaultApplicability = (): MemoryApplicability => ({
    consumer_profiles: [],
    exclude_consumer_profiles: [],
    agent_slugs: [],
    exclude_agent_slugs: [],
    audience_tags: [],
    exclude_audience_tags: [],
  })
  const cloneApplicability = (
    value: MemoryApplicability | undefined,
  ): MemoryApplicability => ({
    ...defaultApplicability(),
    ...(value || {}),
    consumer_profiles: [...(value?.consumer_profiles || [])],
    exclude_consumer_profiles: [...(value?.exclude_consumer_profiles || [])],
    agent_slugs: [...(value?.agent_slugs || [])],
    exclude_agent_slugs: [...(value?.exclude_agent_slugs || [])],
    audience_tags: [...(value?.audience_tags || [])],
    exclude_audience_tags: [...(value?.exclude_audience_tags || [])],
  })
  const arraysEqual = (left: string[], right: string[]) =>
    left.length === right.length &&
    left.every((item, index) => item === right[index])
  const applicabilityEqual = (
    left: MemoryApplicability,
    right: MemoryApplicability,
  ) =>
    arraysEqual(left.consumer_profiles, right.consumer_profiles) &&
    arraysEqual(
      left.exclude_consumer_profiles,
      right.exclude_consumer_profiles,
    ) &&
    arraysEqual(left.agent_slugs, right.agent_slugs) &&
    arraysEqual(left.exclude_agent_slugs, right.exclude_agent_slugs) &&
    arraysEqual(left.audience_tags, right.audience_tags) &&
    arraysEqual(left.exclude_audience_tags, right.exclude_audience_tags)

  const [content, setContent] = useState(episode.content)
  const [tier, setTier] = useState<MemoryCategory>(episode.category)
  const [pinned, setPinned] = useState(episode.pinned ?? false)
  const [summary, setSummary] = useState(episode.summary ?? '')
  const [contextKind, setContextKind] = useState<MemoryContextKind>(
    episode.context_kind ?? 'reference',
  )
  const [applicability, setApplicability] = useState<MemoryApplicability>(
    cloneApplicability(episode.applicability),
  )
  const [triggerTaskTypes] = useState<string[]>(
    episode.trigger_task_types ?? [],
  )
  const [triggerPhases, setTriggerPhases] = useState<string[]>(
    episode.trigger_phases ?? [],
  )
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const initialApplicability = cloneApplicability(episode.applicability)
  const initialTriggerPhases = episode.trigger_phases ?? []

  const hasChanges =
    content !== episode.content ||
    tier !== episode.category ||
    pinned !== (episode.pinned ?? false) ||
    summary !== (episode.summary ?? '') ||
    contextKind !== (episode.context_kind ?? 'reference') ||
    !applicabilityEqual(applicability, initialApplicability) ||
    !arraysEqual(triggerPhases, initialTriggerPhases)

  async function handleSave() {
    if (!hasChanges) {
      onClose()
      return
    }

    setIsSaving(true)
    setError(null)

    try {
      const contentOrTierChanged =
        content !== episode.content || tier !== episode.category
      const pinnedChanged = pinned !== (episode.pinned ?? false)
      const summaryChanged = summary !== (episode.summary ?? '')

      let newUuid = episode.uuid

      // If content or tier changed, need delete+create flow
      if (contentOrTierChanged) {
        // Step 1: Create new episode with preserved stats
        const newEpisode = await addEpisode({
          content,
          source: episode.source,
          source_description: episode.source_description,
          injection_tier: tier,
          context_kind: contextKind,
          applicability,
          preserve_stats_from: episode.uuid,
        })
        newUuid = newEpisode.uuid

        // Step 2: Delete original episode
        await deleteMemory(episode.uuid)
      }

      // Update properties on the (possibly new) episode
      const propsToUpdate: {
        pinned?: boolean
        summary?: string
        trigger_task_types?: string[]
        trigger_phases?: string[]
        context_kind?: MemoryContextKind
        applicability?: MemoryApplicability
      } = {}
      if (pinnedChanged || (contentOrTierChanged && pinned)) {
        propsToUpdate.pinned = pinned
      }
      if (summaryChanged || (contentOrTierChanged && summary)) {
        propsToUpdate.summary = summary
      }
      if (
        !arraysEqual(triggerTaskTypes, episode.trigger_task_types ?? []) ||
        contentOrTierChanged
      ) {
        propsToUpdate.trigger_task_types = triggerTaskTypes
      }
      if (
        !arraysEqual(triggerPhases, initialTriggerPhases) ||
        contentOrTierChanged
      ) {
        propsToUpdate.trigger_phases = triggerPhases
      }
      if (
        contextKind !== (episode.context_kind ?? 'reference') ||
        contentOrTierChanged
      ) {
        propsToUpdate.context_kind = contextKind
      }
      if (
        !applicabilityEqual(applicability, initialApplicability) ||
        contentOrTierChanged
      ) {
        propsToUpdate.applicability = applicability
      }
      if (Object.keys(propsToUpdate).length > 0) {
        await updateEpisodeProperties(newUuid, propsToUpdate)
      }

      // Success - close modal and trigger refresh
      onSaved()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save changes')
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
  }
}
