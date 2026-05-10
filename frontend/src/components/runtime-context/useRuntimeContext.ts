'use client'

import type {
  DragEndEvent,
  DragStartEvent,
  UniqueIdentifier,
} from '@dnd-kit/core'
import { arrayMove } from '@dnd-kit/sortable'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useToast } from '@/components/error/toast'
import { fetchPrompts, type Prompt, updatePrompt } from '@/lib/api/prompts'
import {
  fetchRuntimeOverrides,
  fetchRuntimePreview,
  type RuntimeContextBlock,
  type RuntimeContextOverride,
  type RuntimeContextOverridePayload,
  type RuntimeContextPreview,
  replaceRuntimeOverrides,
} from '@/lib/api/runtime-context'
import { fetchMemoryList, updateEpisodeTier } from '@/lib/memory/episodes'
import type { MemoryCategory, MemoryEpisode } from '@/lib/memory-types'
import {
  blockKey,
  blocksToOverrides,
  type EffectiveRenderMode,
  excludeBlock,
  parseDragId,
  pinBlock,
  reorderBlocks,
  restoreBlock,
  setRenderMode,
  unpinBlock,
} from './resolver'

const DEFAULT_PROFILE = 'agent_startup'

type Tier = 'mandate' | 'guardrail' | 'capability' | 'reference' | 'archive'

function memoryToBlock(episode: MemoryEpisode): RuntimeContextBlock {
  const category: MemoryCategory = episode.category ?? 'reference'
  const tier: Tier = (category as Tier) ?? 'reference'
  const title =
    episode.summary?.trim() ||
    episode.name?.trim() ||
    episode.content.slice(0, 80)
  // Approximate token count for library rows so the user sees consistent numbers
  // before the row is pulled into the rendered pane.
  const tokenCount = Math.max(1, Math.round(episode.content.length / 4))
  return {
    id: `memory:${episode.uuid}`,
    source_type: 'memory',
    source_id: episode.uuid,
    title,
    content: episode.content,
    token_count: tokenCount,
    origin: 'auto',
    source: 'auto',
    auto_reason: `tier:${tier}`,
    mode: 'order',
    position: 0,
    tier,
    render_tier: null,
    render_mode: episode.render_mode ?? null,
    tier_override: null,
    scope: episode.scope ?? 'global',
    scope_id: episode.scope_id ?? null,
    tags: episode.tags ?? [],
  }
}

function promptToBlock(prompt: Prompt): RuntimeContextBlock {
  const tokenCount = Math.max(1, Math.round(prompt.content.length / 4))
  return {
    id: `prompt:${prompt.slug}`,
    source_type: 'prompt',
    source_id: prompt.slug,
    title: prompt.name,
    content: prompt.content,
    token_count: tokenCount,
    origin: prompt.boot_eligible ? 'auto' : 'override',
    source: prompt.boot_eligible ? 'auto' : 'pinned',
    auto_reason: prompt.boot_eligible ? 'boot_eligible' : null,
    mode: 'order',
    position: 0,
    tier: null,
    render_tier: null,
    render_mode: null,
    tier_override: null,
    scope: prompt.is_global ? 'global' : 'agent',
    scope_id: null,
    tags:
      prompt.prompt_type && prompt.prompt_type !== 'standard'
        ? [prompt.prompt_type]
        : [],
  }
}

function overridesFromResponse(
  rows: RuntimeContextOverride[],
): RuntimeContextOverridePayload[] {
  return blocksToOverrides(rows)
}

export function useRuntimeContext(
  profile: string = DEFAULT_PROFILE,
  projectId: string | null = null,
) {
  const queryClient = useQueryClient()
  const { addToast } = useToast()

  // projectId scopes the project layer of overrides + the auxiliary blocks
  // (project_index, tool_capabilities) that the preview includes. Passing null
  // matches global / no-project session-start behavior.
  const projectKey = projectId ?? null
  const overridesQuery = useQuery({
    queryKey: ['runtime-context', 'overrides', profile, projectKey],
    queryFn: () =>
      fetchRuntimeOverrides({
        consumerProfile: profile,
        projectId: projectId ?? undefined,
      }),
  })
  const previewQuery = useQuery({
    queryKey: ['runtime-context', 'preview', profile, projectKey],
    queryFn: () =>
      fetchRuntimePreview({
        consumerProfile: profile,
        projectId: projectId ?? undefined,
      }),
  })
  const memoriesQuery = useQuery({
    queryKey: ['memory', 'runtime-library'],
    queryFn: () => fetchMemoryList({ limit: 1000, allGroups: true }),
  })
  const promptsQuery = useQuery({
    queryKey: ['prompts'],
    queryFn: () => fetchPrompts(),
  })

  const [draftOverrides, setDraftOverrides] = useState<
    RuntimeContextOverridePayload[]
  >([])
  const undoSnapshot = useRef<RuntimeContextOverridePayload[] | null>(null)
  const reorderTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [activeDragId, setActiveDragId] = useState<UniqueIdentifier | null>(
    null,
  )

  useEffect(() => {
    if (overridesQuery.data) {
      setDraftOverrides(overridesFromResponse(overridesQuery.data))
    }
  }, [overridesQuery.data])

  const saveMutation = useMutation({
    mutationFn: (overrides: RuntimeContextOverridePayload[]) =>
      replaceRuntimeOverrides({
        consumerProfile: profile,
        projectId: projectId ?? undefined,
        overrides,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['runtime-context', 'overrides', profile, projectKey],
      })
      queryClient.invalidateQueries({
        queryKey: ['runtime-context', 'preview', profile, projectKey],
      })
    },
    onError: (error) => {
      addToast({
        type: 'error',
        title: 'Save failed',
        message: error instanceof Error ? error.message : 'Unknown error',
      })
    },
  })

  const commit = (
    next: RuntimeContextOverridePayload[],
    options?: { undoLabel?: string; debounce?: boolean },
  ) => {
    const previous = draftOverrides
    setDraftOverrides(next)
    const fire = () => saveMutation.mutate(next)
    if (options?.debounce) {
      if (reorderTimer.current) clearTimeout(reorderTimer.current)
      reorderTimer.current = setTimeout(fire, 250)
    } else {
      if (reorderTimer.current) {
        clearTimeout(reorderTimer.current)
        reorderTimer.current = null
      }
      fire()
    }
    if (options?.undoLabel) {
      undoSnapshot.current = previous
      addToast({
        type: 'info',
        title: options.undoLabel,
        duration: 6000,
        action: {
          label: 'Undo',
          onClick: () => {
            const snap = undoSnapshot.current
            if (!snap) return
            undoSnapshot.current = null
            setDraftOverrides(snap)
            saveMutation.mutate(snap)
          },
        },
      })
    }
  }

  const preview: RuntimeContextPreview | undefined = previewQuery.data
  const blocks = preview?.blocks ?? []
  const excludedBlocks = preview?.excluded ?? []

  const inContextKeys = useMemo(() => {
    const set = new Set<string>()
    for (const block of blocks) set.add(blockKey(block))
    for (const block of excludedBlocks) set.add(blockKey(block))
    return set
  }, [blocks, excludedBlocks])

  // Library = full memory + prompt list, with rendered/excluded items dimmed via inContextKeys.
  const library = useMemo<RuntimeContextBlock[]>(() => {
    const memoryBlocks = (memoriesQuery.data?.episodes ?? []).map(memoryToBlock)
    const promptBlocks = (promptsQuery.data ?? []).map(promptToBlock)
    return [...promptBlocks, ...memoryBlocks]
  }, [memoriesQuery.data, promptsQuery.data])

  // Map of source_type:source_id → raw full content, used to swap a rendered row's
  // body to its full source when the user expands a compact/summary row.
  const fullContentLookup = useMemo(() => {
    const map = new Map<string, string>()
    for (const block of library) map.set(blockKey(block), block.content)
    return map
  }, [library])

  const totalCount =
    (memoriesQuery.data?.episodes.length ?? 0) +
    (promptsQuery.data?.length ?? 0)

  const onPin = (block: RuntimeContextBlock) => {
    commit(
      pinBlock(draftOverrides, blocks, block.source_type, block.source_id),
      {
        undoLabel: 'Pinned',
      },
    )
  }

  const onExclude = (block: RuntimeContextBlock) => {
    commit(excludeBlock(draftOverrides, blocks, block), {
      undoLabel: 'Excluded',
    })
  }

  const onRestore = (block: RuntimeContextBlock) => {
    commit(restoreBlock(draftOverrides, block), { undoLabel: 'Restored' })
  }

  const onUnpin = (block: RuntimeContextBlock) => {
    commit(unpinBlock(draftOverrides, block.source_type, block.source_id), {
      undoLabel: 'Unpinned',
    })
  }

  const onRenderModeChange = (
    block: RuntimeContextBlock,
    mode: EffectiveRenderMode,
  ) => {
    commit(setRenderMode(draftOverrides, block, mode), {
      undoLabel: `Render mode → ${mode === 'auto' ? 'Auto' : mode}`,
    })
  }

  const onResetOverrides = () => {
    if (draftOverrides.length === 0) return
    commit([], { undoLabel: 'All overrides cleared' })
  }

  const refreshAfterSourceEdit = () => {
    queryClient.invalidateQueries({ queryKey: ['memory', 'runtime-library'] })
    queryClient.invalidateQueries({ queryKey: ['prompts'] })
    queryClient.invalidateQueries({
      queryKey: ['runtime-context', 'preview', profile, projectKey],
    })
  }

  // Source-of-truth edits (D): change the underlying prompt/memory record so
  // the row's default behavior changes globally — distinct from the per-profile
  // override layer, which only flips visibility for one profile/project.
  const onMakeDefault = async (block: RuntimeContextBlock) => {
    try {
      if (block.source_type === 'prompt') {
        await updatePrompt(block.source_id, { boot_eligible: true })
        addToast({ type: 'info', title: 'Prompt set as boot-eligible' })
      } else {
        await updateEpisodeTier(block.source_id, 'mandate')
        addToast({
          type: 'info',
          title: 'Memory tier set to mandate',
          message: 'Use the edit modal for guardrail / reference.',
        })
      }
      refreshAfterSourceEdit()
    } catch (error) {
      addToast({
        type: 'error',
        title: 'Set default failed',
        message: error instanceof Error ? error.message : 'Unknown error',
      })
    }
  }

  const onRemoveDefault = async (block: RuntimeContextBlock) => {
    try {
      if (block.source_type === 'prompt') {
        await updatePrompt(block.source_id, { boot_eligible: false })
        addToast({ type: 'info', title: 'Prompt removed from boot defaults' })
      } else {
        await updateEpisodeTier(block.source_id, 'archive')
        addToast({ type: 'info', title: 'Memory archived' })
      }
      refreshAfterSourceEdit()
    } catch (error) {
      addToast({
        type: 'error',
        title: 'Remove default failed',
        message: error instanceof Error ? error.message : 'Unknown error',
      })
    }
  }

  const onRefresh = () => {
    overridesQuery.refetch()
    previewQuery.refetch()
    memoriesQuery.refetch()
    promptsQuery.refetch()
  }

  const onDragStart = (event: DragStartEvent) => {
    setActiveDragId(event.active.id)
  }

  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    setActiveDragId(null)
    if (!over) return
    const activeParsed = parseDragId(String(active.id))
    if (!activeParsed) return

    if (activeParsed.kind === 'library') {
      // Drop into rendered pane (zone or another rendered row) -> pin.
      const overId = String(over.id)
      if (overId === 'rendered-zone') {
        commit(
          pinBlock(
            draftOverrides,
            blocks,
            activeParsed.sourceType,
            activeParsed.sourceId,
          ),
          { undoLabel: 'Pinned' },
        )
        return
      }
      if (overId.startsWith('rendered:')) {
        const overParsed = parseDragId(overId)
        if (!overParsed) return
        const targetIndex = blocks.findIndex(
          (block) =>
            block.source_type === overParsed.sourceType &&
            block.source_id === overParsed.sourceId,
        )
        const targetPosition =
          targetIndex >= 0 ? blocks[targetIndex].position : undefined
        commit(
          pinBlock(
            draftOverrides,
            blocks,
            activeParsed.sourceType,
            activeParsed.sourceId,
            targetPosition !== undefined
              ? Math.max(1, targetPosition - 1)
              : undefined,
          ),
          { undoLabel: 'Pinned' },
        )
        return
      }
      return
    }

    // Active is rendered.
    const overId = String(over.id)
    if (overId === 'library-zone' || overId.startsWith('lib-row:')) {
      const block = blocks.find(
        (b) =>
          b.source_type === activeParsed.sourceType &&
          b.source_id === activeParsed.sourceId,
      )
      if (block) {
        commit(unpinBlock(draftOverrides, block.source_type, block.source_id), {
          undoLabel: 'Unpinned',
        })
      }
      return
    }
    if (overId.startsWith('rendered:')) {
      const overParsed = parseDragId(overId)
      if (!overParsed) return
      // Reorder against the combined visible list so excluded rows keep their
      // place in the position sequence instead of sinking to the bottom.
      const combined = [...blocks, ...excludedBlocks].sort(
        (a, b) => a.position - b.position,
      )
      const fromIndex = combined.findIndex(
        (block) =>
          block.source_type === activeParsed.sourceType &&
          block.source_id === activeParsed.sourceId,
      )
      const toIndex = combined.findIndex(
        (block) =>
          block.source_type === overParsed.sourceType &&
          block.source_id === overParsed.sourceId,
      )
      if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return
      const reordered = arrayMove(combined, fromIndex, toIndex)
      commit(reorderBlocks(draftOverrides, reordered), {
        undoLabel: 'Reordered',
        debounce: true,
      })
    }
  }

  const isLoading = overridesQuery.isLoading || previewQuery.isLoading

  // Avoid telling the unused-suggested-export warning systems we exported onUnpin
  // accidentally — it's available for callers who want a button-driven unpin, but
  // the main UX is drag-and-drop.
  void onUnpin

  return {
    profile,
    isLoading,
    saving: saveMutation.isPending,
    preview,
    blocks,
    excludedBlocks,
    library,
    fullContentLookup,
    totalCount,
    inContextKeys,
    draftOverrides,
    activeDragId,
    episodes: memoriesQuery.data?.episodes ?? [],
    prompts: promptsQuery.data ?? [],
    onPin,
    onExclude,
    onRestore,
    onRenderModeChange,
    onResetOverrides,
    onRefresh,
    onDragStart,
    onDragEnd,
    onMakeDefault,
    onRemoveDefault,
  }
}
