'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BrainCircuit,
  Eye,
  GripVertical,
  Loader2,
  MinusCircle,
  Plus,
  RefreshCw,
  ScrollText,
  Search,
} from 'lucide-react'
import Link from 'next/link'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useToast } from '@/components/error/toast'
import { fetchPrompts } from '@/lib/api/prompts'
import {
  fetchRuntimeOverrides,
  fetchRuntimePreview,
  type RuntimeContextBlock,
  type RuntimeContextOverridePayload,
  type RuntimeOverrideMode,
  type RuntimeSourceType,
  type RuntimeTierOverride,
  replaceRuntimeOverrides,
} from '@/lib/api/runtime-context'
import { fetchMemoryList } from '@/lib/memory/episodes'
import type { MemoryEpisode } from '@/lib/memory-types'
import { cn } from '@/lib/utils'

// The boot context is generic across CLIs; profile is fixed at the API layer.
const CONSUMER_PROFILE = 'codex_startup'

type RenderMode = 'auto' | 'full' | 'compact' | 'summary'

const RENDER_MODE_TO_TIER: Record<
  Exclude<RenderMode, 'auto'>,
  RuntimeTierOverride
> = {
  full: 'L2',
  compact: 'L1',
  summary: 'L0',
}

const TIER_TO_RENDER_MODE: Record<RuntimeTierOverride, RenderMode> = {
  L2: 'full',
  L1: 'compact',
  L0: 'summary',
}

function overrideKey(sourceType: RuntimeSourceType, sourceId: string) {
  return `${sourceType}:${sourceId}`
}

function blockKey(block: RuntimeContextBlock) {
  return overrideKey(block.source_type, block.source_id)
}

function displayMemory(memory: MemoryEpisode) {
  return memory.summary || memory.name || memory.content.slice(0, 80)
}

function nextPosition(
  blocks: RuntimeContextBlock[],
  overrides: RuntimeContextOverridePayload[],
) {
  const maxBlock = blocks.reduce(
    (max, block) => Math.max(max, block.position),
    0,
  )
  const maxOverride = overrides.reduce(
    (max, item) => Math.max(max, item.position),
    0,
  )
  return Math.max(maxBlock, maxOverride, 0) + 10
}

export default function RuntimeContextPage() {
  const queryClient = useQueryClient()
  const { addToast } = useToast()
  const [draftOverrides, setDraftOverrides] = useState<
    RuntimeContextOverridePayload[]
  >([])
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [addSelection, setAddSelection] = useState('')
  const undoSnapshot = useRef<RuntimeContextOverridePayload[] | null>(null)

  const overridesQuery = useQuery({
    queryKey: ['runtime-context', 'overrides', CONSUMER_PROFILE],
    queryFn: () => fetchRuntimeOverrides({ consumerProfile: CONSUMER_PROFILE }),
  })

  useEffect(() => {
    setDraftOverrides(
      (overridesQuery.data ?? []).map((item) => ({
        source_type: item.source_type,
        source_id: item.source_id,
        mode: item.mode,
        position: item.position,
        enabled: item.enabled,
        note: item.note,
        tier_override: item.tier_override ?? null,
      })),
    )
  }, [overridesQuery.data])

  const previewQuery = useQuery({
    queryKey: ['runtime-context', 'preview', CONSUMER_PROFILE],
    queryFn: () => fetchRuntimePreview({ consumerProfile: CONSUMER_PROFILE }),
  })

  const promptsQuery = useQuery({
    queryKey: ['prompts'],
    queryFn: () => fetchPrompts(),
  })

  const memoriesQuery = useQuery({
    queryKey: ['memory', 'runtime-context-picker'],
    queryFn: () => fetchMemoryList({ limit: 300, allGroups: true }),
  })

  const saveMutation = useMutation({
    mutationFn: (overrides: RuntimeContextOverridePayload[]) =>
      replaceRuntimeOverrides({
        consumerProfile: CONSUMER_PROFILE,
        overrides,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['runtime-context', 'overrides'],
      })
      queryClient.invalidateQueries({
        queryKey: ['runtime-context', 'preview'],
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

  const preview = previewQuery.data
  const blocks = preview?.blocks ?? []

  const draftByKey = useMemo(() => {
    const map = new Map<string, RuntimeContextOverridePayload>()
    for (const item of draftOverrides) {
      map.set(overrideKey(item.source_type, item.source_id), item)
    }
    return map
  }, [draftOverrides])

  const filteredBlocks = useMemo(() => {
    const needle = searchTerm.trim().toLowerCase()
    if (!needle) return blocks
    return blocks.filter((block) => {
      const haystack = `${block.title} ${block.content} ${block.source_id}`
      return haystack.toLowerCase().includes(needle)
    })
  }, [blocks, searchTerm])

  const saveOverrides = (
    next: RuntimeContextOverridePayload[],
    options?: { undoLabel?: string },
  ) => {
    const previous = draftOverrides
    const normalized = next
      .filter((item) => item.source_id.trim())
      .map((item, index) => ({
        ...item,
        position: item.position || (index + 1) * 10,
        enabled: item.enabled,
        note: item.note || null,
      }))
    setDraftOverrides(normalized)
    saveMutation.mutate(normalized)
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

  const upsertOverride = (
    sourceType: RuntimeSourceType,
    sourceId: string,
    mode: RuntimeOverrideMode,
    position?: number,
    undoLabel?: string,
  ) => {
    const key = overrideKey(sourceType, sourceId)
    const existing = draftByKey.get(key)
    const next = [
      ...draftOverrides.filter(
        (item) => overrideKey(item.source_type, item.source_id) !== key,
      ),
      {
        source_type: sourceType,
        source_id: sourceId,
        mode,
        position:
          position ??
          existing?.position ??
          nextPosition(blocks, draftOverrides),
        enabled: true,
        note: existing?.note ?? null,
        tier_override: existing?.tier_override ?? null,
      },
    ].sort((a, b) => a.position - b.position)
    saveOverrides(next, undoLabel ? { undoLabel } : undefined)
  }

  const clearOverride = (
    sourceType: RuntimeSourceType,
    sourceId: string,
    undoLabel?: string,
  ) => {
    const key = overrideKey(sourceType, sourceId)
    saveOverrides(
      draftOverrides.filter(
        (item) => overrideKey(item.source_type, item.source_id) !== key,
      ),
      undoLabel ? { undoLabel } : undefined,
    )
  }

  const setBlockRenderMode = (block: RuntimeContextBlock, mode: RenderMode) => {
    const key = blockKey(block)
    const existing = draftByKey.get(key)
    const tier = mode === 'auto' ? null : RENDER_MODE_TO_TIER[mode]

    if (
      tier === null &&
      (!existing ||
        (existing.mode !== 'include' && existing.mode !== 'exclude'))
    ) {
      // No tier override and no other reason to keep a row; drop it entirely.
      clearOverride(block.source_type, block.source_id, 'Render mode reset')
      return
    }

    const merged: RuntimeContextOverridePayload = {
      source_type: block.source_type,
      source_id: block.source_id,
      mode: existing?.mode ?? 'order',
      position: existing?.position ?? block.position,
      enabled: existing?.enabled ?? true,
      note: existing?.note ?? null,
      tier_override: tier,
    }
    const replaced = draftOverrides.filter(
      (item) => overrideKey(item.source_type, item.source_id) !== key,
    )
    saveOverrides(
      [...replaced, merged].sort((a, b) => a.position - b.position),
      {
        undoLabel: `Render mode → ${mode === 'auto' ? 'Auto' : mode}`,
      },
    )
  }

  const toggleExclude = (block: RuntimeContextBlock) => {
    const explicit = draftByKey.get(blockKey(block))
    if (explicit?.mode === 'exclude') {
      // Re-include: drop override entirely if no tier preference, else flip mode to order.
      if (explicit.tier_override) {
        upsertOverride(
          block.source_type,
          block.source_id,
          'order',
          explicit.position,
          'Re-included',
        )
      } else {
        clearOverride(block.source_type, block.source_id, 'Re-included')
      }
    } else {
      upsertOverride(
        block.source_type,
        block.source_id,
        'exclude',
        block.position,
        'Excluded from boot context',
      )
    }
  }

  const saveBlockOrder = (orderedBlocks: RuntimeContextBlock[]) => {
    const orderedKeys = new Set(orderedBlocks.map(blockKey))
    const orderedOverrides = orderedBlocks.map((block, index) => {
      const existing = draftByKey.get(blockKey(block))
      const mode: RuntimeOverrideMode =
        block.source_type === 'prompt'
          ? 'include'
          : existing?.mode === 'include'
            ? 'include'
            : 'order'
      return {
        source_type: block.source_type,
        source_id: block.source_id,
        mode,
        position: (index + 1) * 10,
        enabled: true,
        note: existing?.note ?? null,
        tier_override: existing?.tier_override ?? null,
      }
    })
    const hiddenOverrides = draftOverrides.filter(
      (item) => !orderedKeys.has(overrideKey(item.source_type, item.source_id)),
    )
    saveOverrides([...orderedOverrides, ...hiddenOverrides], {
      undoLabel: 'Reordered',
    })
  }

  const handleDrop = (targetId: string) => {
    if (!draggingId || draggingId === targetId) return
    // Drag operates on the unfiltered list to keep positions stable.
    const fromIndex = blocks.findIndex((block) => block.id === draggingId)
    const toIndex = blocks.findIndex((block) => block.id === targetId)
    if (fromIndex < 0 || toIndex < 0) return
    const ordered = [...blocks]
    const [moved] = ordered.splice(fromIndex, 1)
    ordered.splice(toIndex, 0, moved)
    setDraggingId(null)
    saveBlockOrder(ordered)
  }

  const promptOptions = (promptsQuery.data ?? []).filter(
    (prompt) => !draftByKey.has(overrideKey('prompt', prompt.slug)),
  )
  const memoryOptions = (memoriesQuery.data?.episodes ?? []).filter(
    (memory) => !draftByKey.has(overrideKey('memory', memory.uuid)),
  )

  const handleAdd = (value: string) => {
    if (!value) return
    const [type, ...rest] = value.split(':')
    const id = rest.join(':')
    if (type === 'prompt' && id) {
      upsertOverride('prompt', id, 'include', 10, 'Prompt added')
    } else if (type === 'memory' && id) {
      upsertOverride('memory', id, 'include', undefined, 'Memory added')
    }
    setAddSelection('')
  }

  const isLoading = overridesQuery.isLoading || previewQuery.isLoading

  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />

      <header className="page-header">
        <div className="page-container px-4 lg:px-8">
          <div className="page-header-row">
            <div className="page-title-group">
              <div className="page-title-icon">
                <BrainCircuit className="h-5 w-5" />
              </div>
              <div className="page-title-stack">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="page-title">Runtime Context</h1>
                  <span className="page-pill">
                    {preview?.total_tokens ?? 0} tokens
                  </span>
                </div>
                <div className="page-meta">
                  <span>
                    Boot context injected into every CLI session by Agent Hub.
                  </span>
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={() => {
                overridesQuery.refetch()
                previewQuery.refetch()
              }}
              className="button-secondary"
            >
              <RefreshCw className="h-4 w-4" />
              Refresh
            </button>
          </div>
        </div>
      </header>

      <main className="page-frame">
        <div className="page-container space-y-5">
          <section className="control-strip animate-fade-up">
            <label className="relative flex-[2] text-xs font-medium text-slate-400">
              <span className="sr-only">Search blocks</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                className="control-input pl-9"
                placeholder="Search blocks…"
              />
            </label>
            <label className="min-w-72 flex-1 text-xs font-medium text-slate-400">
              <span className="sr-only">Add to boot context</span>
              <select
                value={addSelection}
                onChange={(event) => handleAdd(event.target.value)}
                className="control-select w-full"
              >
                <option value="">+ Add to boot context…</option>
                {promptOptions.length > 0 && (
                  <optgroup label="Prompts">
                    {promptOptions.map((prompt) => (
                      <option key={prompt.slug} value={`prompt:${prompt.slug}`}>
                        {prompt.name}
                      </option>
                    ))}
                  </optgroup>
                )}
                {memoryOptions.length > 0 && (
                  <optgroup label="Memories">
                    {memoryOptions.map((memory) => (
                      <option key={memory.uuid} value={`memory:${memory.uuid}`}>
                        {displayMemory(memory)}
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
            </label>
          </section>

          {isLoading ? (
            <div className="flex min-h-[38vh] items-center justify-center">
              <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
            </div>
          ) : (
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(420px,0.95fr)]">
              <section className="panel-surface animate-fade-up stagger-2">
                <div className="flex items-center justify-between border-b border-slate-800/70 px-4 py-3">
                  <div className="flex items-center gap-2">
                    <ScrollText className="h-4 w-4 text-amber-300" />
                    <h2 className="text-sm font-semibold text-slate-100">
                      Injection Order
                    </h2>
                  </div>
                  <span className="text-xs text-slate-500">
                    {searchTerm.trim()
                      ? `${filteredBlocks.length} of ${blocks.length}`
                      : `${blocks.length} blocks`}
                  </span>
                </div>
                <div className="divide-y divide-slate-800/70">
                  {filteredBlocks.length === 0 ? (
                    <div className="px-4 py-10 text-center text-sm text-slate-500">
                      {searchTerm.trim()
                        ? 'No blocks match your search.'
                        : 'No blocks resolved.'}
                    </div>
                  ) : (
                    filteredBlocks.map((block) => {
                      const key = blockKey(block)
                      const explicit = draftByKey.get(key)
                      const excluded = explicit?.mode === 'exclude'
                      const renderMode: RenderMode = explicit?.tier_override
                        ? TIER_TO_RENDER_MODE[explicit.tier_override]
                        : 'auto'
                      return (
                        <div
                          key={block.id}
                          draggable={!searchTerm.trim()}
                          onDragStart={() => setDraggingId(block.id)}
                          onDragEnd={() => setDraggingId(null)}
                          onDragOver={(event) => event.preventDefault()}
                          onDrop={() => handleDrop(block.id)}
                          className={cn(
                            'flex gap-3 px-4 py-3 transition',
                            draggingId === block.id && 'bg-slate-800/50',
                            excluded && 'opacity-50',
                          )}
                        >
                          <div
                            className={cn(
                              'flex pt-1 text-slate-500',
                              searchTerm.trim()
                                ? 'cursor-not-allowed opacity-30'
                                : 'cursor-grab',
                            )}
                            title={
                              searchTerm.trim()
                                ? 'Clear search to reorder'
                                : 'Drag to reorder'
                            }
                          >
                            <GripVertical className="h-4 w-4" />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              {block.source_type === 'prompt' ? (
                                <Link
                                  href={`/prompts/${block.source_id}`}
                                  className="truncate text-sm font-semibold text-slate-100 hover:text-amber-300"
                                >
                                  {block.title}
                                </Link>
                              ) : (
                                <h3 className="truncate text-sm font-semibold text-slate-100">
                                  {block.title}
                                </h3>
                              )}
                              <span className="rounded-full border border-slate-700/70 px-2 py-0.5 text-[10px] uppercase text-slate-400">
                                {block.source_type}
                              </span>
                              {block.origin === 'override' && !excluded && (
                                <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] uppercase text-amber-300">
                                  override
                                </span>
                              )}
                              {excluded && (
                                <span className="rounded-full bg-rose-500/15 px-2 py-0.5 text-[10px] uppercase text-rose-300">
                                  excluded
                                </span>
                              )}
                            </div>
                            <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-400">
                              {block.content}
                            </p>
                            <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
                              <span>{block.token_count} tok</span>
                              {block.source_type === 'memory' && (
                                <label className="ml-auto flex items-center gap-1.5 text-slate-400">
                                  Render
                                  <select
                                    value={renderMode}
                                    onChange={(event) =>
                                      setBlockRenderMode(
                                        block,
                                        event.target.value as RenderMode,
                                      )
                                    }
                                    className="control-select py-0.5 text-[11px]"
                                  >
                                    <option value="auto">Auto</option>
                                    <option value="full">Full</option>
                                    <option value="compact">Compact</option>
                                    <option value="summary">Summary</option>
                                  </select>
                                </label>
                              )}
                            </div>
                          </div>
                          <div className="flex items-start">
                            <button
                              type="button"
                              title={excluded ? 'Re-include' : 'Exclude'}
                              className="icon-button h-9 w-9"
                              onClick={() => toggleExclude(block)}
                            >
                              {excluded ? (
                                <Plus className="h-4 w-4" />
                              ) : (
                                <MinusCircle className="h-4 w-4" />
                              )}
                            </button>
                          </div>
                        </div>
                      )
                    })
                  )}
                </div>
              </section>

              <section className="panel-surface animate-fade-up stagger-3 xl:sticky xl:top-4 xl:max-h-[calc(100vh-6rem)] xl:self-start">
                <div className="flex items-center justify-between border-b border-slate-800/70 px-4 py-3">
                  <div className="flex items-center gap-2">
                    <Eye className="h-4 w-4 text-sky-300" />
                    <h2 className="text-sm font-semibold text-slate-100">
                      Rendered
                    </h2>
                  </div>
                  <span className="text-xs text-slate-500">
                    {saveMutation.isPending
                      ? 'saving…'
                      : `${preview?.total_tokens ?? 0} tokens`}
                  </span>
                </div>
                <pre className="overflow-auto whitespace-pre-wrap px-4 py-4 font-mono text-xs leading-5 text-slate-300 xl:max-h-[calc(100vh-10rem)]">
                  {preview?.rendered || 'No context rendered.'}
                </pre>
              </section>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
