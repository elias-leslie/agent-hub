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
  Save,
  ScrollText,
  Trash2,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { fetchPrompts } from '@/lib/api/prompts'
import {
  fetchRuntimeOverrides,
  fetchRuntimePreview,
  fetchRuntimeProfiles,
  type RuntimeContextBlock,
  type RuntimeContextOverridePayload,
  type RuntimeOverrideMode,
  type RuntimeSourceType,
  replaceRuntimeOverrides,
} from '@/lib/api/runtime-context'
import { fetchMemoryList } from '@/lib/memory/episodes'
import type { MemoryEpisode } from '@/lib/memory-types'
import { cn } from '@/lib/utils'

const DEFAULT_PROFILE = 'codex_startup'
const DEFAULT_QUERY = 'startup context'

function overrideKey(sourceType: RuntimeSourceType, sourceId: string) {
  return `${sourceType}:${sourceId}`
}

function blockKey(block: RuntimeContextBlock) {
  return overrideKey(block.source_type, block.source_id)
}

function displayMemory(memory: MemoryEpisode) {
  return memory.summary || memory.name || memory.content.slice(0, 90)
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

function modeLabel(mode: RuntimeOverrideMode) {
  return mode === 'include'
    ? 'include'
    : mode === 'exclude'
      ? 'exclude'
      : 'order'
}

export default function RuntimeContextPage() {
  const queryClient = useQueryClient()
  const [consumerProfile, setConsumerProfile] = useState(DEFAULT_PROFILE)
  const [projectId, setProjectId] = useState('summitflow')
  const [query, setQuery] = useState(DEFAULT_QUERY)
  const [taskType, setTaskType] = useState('')
  const [phase, setPhase] = useState('')
  const [includeGlobal, setIncludeGlobal] = useState(true)
  const [draftOverrides, setDraftOverrides] = useState<
    RuntimeContextOverridePayload[]
  >([])
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const [promptSlug, setPromptSlug] = useState('')
  const [memoryUuid, setMemoryUuid] = useState('')

  const normalizedProjectId = projectId.trim() || undefined

  const profilesQuery = useQuery({
    queryKey: ['runtime-context', 'profiles'],
    queryFn: fetchRuntimeProfiles,
  })

  const overridesQuery = useQuery({
    queryKey: [
      'runtime-context',
      'overrides',
      consumerProfile,
      normalizedProjectId,
    ],
    queryFn: () =>
      fetchRuntimeOverrides({
        consumerProfile,
        projectId: normalizedProjectId,
      }),
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
      })),
    )
  }, [overridesQuery.data])

  const previewQuery = useQuery({
    queryKey: [
      'runtime-context',
      'preview',
      consumerProfile,
      normalizedProjectId,
      query,
      taskType,
      phase,
      includeGlobal,
    ],
    queryFn: () =>
      fetchRuntimePreview({
        consumerProfile,
        projectId: normalizedProjectId,
        query,
        taskType: taskType.trim() || undefined,
        phase: phase.trim() || undefined,
        includeGlobal,
      }),
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
        consumerProfile,
        projectId: normalizedProjectId,
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

  const saveOverrides = (next: RuntimeContextOverridePayload[]) => {
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
  }

  const upsertOverride = (
    sourceType: RuntimeSourceType,
    sourceId: string,
    mode: RuntimeOverrideMode,
    position?: number,
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
      },
    ].sort((a, b) => a.position - b.position)
    saveOverrides(next)
  }

  const removeOverride = (sourceType: RuntimeSourceType, sourceId: string) => {
    const key = overrideKey(sourceType, sourceId)
    saveOverrides(
      draftOverrides.filter(
        (item) => overrideKey(item.source_type, item.source_id) !== key,
      ),
    )
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
      }
    })
    const hiddenOverrides = draftOverrides.filter(
      (item) => !orderedKeys.has(overrideKey(item.source_type, item.source_id)),
    )
    saveOverrides([...orderedOverrides, ...hiddenOverrides])
  }

  const handleDrop = (targetId: string) => {
    if (!draggingId || draggingId === targetId) return
    const fromIndex = blocks.findIndex((block) => block.id === draggingId)
    const toIndex = blocks.findIndex((block) => block.id === targetId)
    if (fromIndex < 0 || toIndex < 0) return
    const ordered = [...blocks]
    const [moved] = ordered.splice(fromIndex, 1)
    ordered.splice(toIndex, 0, moved)
    setDraggingId(null)
    saveBlockOrder(ordered)
  }

  const forcedPromptOptions = (promptsQuery.data ?? []).filter(
    (prompt) => !draftByKey.has(overrideKey('prompt', prompt.slug)),
  )
  const memoryOptions = memoriesQuery.data?.episodes ?? []

  const isLoading =
    profilesQuery.isLoading ||
    overridesQuery.isLoading ||
    previewQuery.isLoading

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
                  <span>Codex, Claude, Gemini startup injection.</span>
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
            <label className="min-w-52 flex-1 text-xs font-medium text-slate-400">
              Profile
              <select
                value={consumerProfile}
                onChange={(event) => setConsumerProfile(event.target.value)}
                className="control-select mt-1 w-full"
              >
                {(
                  profilesQuery.data ?? [
                    {
                      consumer_profile: DEFAULT_PROFILE,
                      label: 'Codex Startup',
                    },
                  ]
                ).map((profile) => (
                  <option
                    key={profile.consumer_profile}
                    value={profile.consumer_profile}
                  >
                    {profile.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="min-w-48 flex-1 text-xs font-medium text-slate-400">
              Project
              <input
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
                className="control-input mt-1"
                placeholder="global"
              />
            </label>
            <label className="min-w-56 flex-[2] text-xs font-medium text-slate-400">
              Query
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="control-input mt-1"
                placeholder={DEFAULT_QUERY}
              />
            </label>
            <label className="inline-flex items-center gap-2 pt-5 text-xs font-medium text-slate-300">
              <input
                type="checkbox"
                checked={includeGlobal}
                onChange={(event) => setIncludeGlobal(event.target.checked)}
                className="h-4 w-4 rounded border-slate-700 bg-slate-900"
              />
              Global
            </label>
          </section>

          <section className="control-strip animate-fade-up stagger-1">
            <label className="min-w-48 flex-1 text-xs font-medium text-slate-400">
              Task Type
              <input
                value={taskType}
                onChange={(event) => setTaskType(event.target.value)}
                className="control-input mt-1"
                placeholder="optional"
              />
            </label>
            <label className="min-w-48 flex-1 text-xs font-medium text-slate-400">
              Phase
              <input
                value={phase}
                onChange={(event) => setPhase(event.target.value)}
                className="control-input mt-1"
                placeholder="optional"
              />
            </label>
            <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-end">
              <label className="min-w-48 flex-1 text-xs font-medium text-slate-400">
                Force Prompt
                <select
                  value={promptSlug}
                  onChange={(event) => setPromptSlug(event.target.value)}
                  className="control-select mt-1 w-full"
                >
                  <option value="">Select prompt</option>
                  {forcedPromptOptions.map((prompt) => (
                    <option key={prompt.slug} value={prompt.slug}>
                      {prompt.name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="button-secondary"
                disabled={!promptSlug}
                onClick={() => {
                  upsertOverride('prompt', promptSlug, 'include', 10)
                  setPromptSlug('')
                }}
              >
                <Plus className="h-4 w-4" />
                Prompt
              </button>
            </div>
            <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-end">
              <label className="min-w-56 flex-1 text-xs font-medium text-slate-400">
                Force Memory
                <select
                  value={memoryUuid}
                  onChange={(event) => setMemoryUuid(event.target.value)}
                  className="control-select mt-1 w-full"
                >
                  <option value="">Select memory</option>
                  {memoryOptions.map((memory) => (
                    <option key={memory.uuid} value={memory.uuid}>
                      {displayMemory(memory)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="button-secondary"
                disabled={!memoryUuid}
                onClick={() => {
                  upsertOverride('memory', memoryUuid, 'include')
                  setMemoryUuid('')
                }}
              >
                <Plus className="h-4 w-4" />
                Memory
              </button>
            </div>
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
                    {blocks.length} blocks
                  </span>
                </div>
                <div className="divide-y divide-slate-800/70">
                  {blocks.map((block) => {
                    const key = blockKey(block)
                    const explicit = draftByKey.get(key)
                    return (
                      <div
                        key={block.id}
                        draggable
                        onDragStart={() => setDraggingId(block.id)}
                        onDragEnd={() => setDraggingId(null)}
                        onDragOver={(event) => event.preventDefault()}
                        onDrop={() => handleDrop(block.id)}
                        className={cn(
                          'flex gap-3 px-4 py-3 transition',
                          draggingId === block.id && 'bg-slate-800/50',
                        )}
                      >
                        <div className="flex pt-1 text-slate-500">
                          <GripVertical className="h-4 w-4" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="truncate text-sm font-semibold text-slate-100">
                              {block.title}
                            </h3>
                            <span className="rounded-full border border-slate-700/70 px-2 py-0.5 text-[10px] uppercase text-slate-400">
                              {block.source_type}
                            </span>
                            <span
                              className={cn(
                                'rounded-full px-2 py-0.5 text-[10px] uppercase',
                                block.origin === 'override'
                                  ? 'bg-amber-500/15 text-amber-300'
                                  : 'bg-slate-800 text-slate-400',
                              )}
                            >
                              {explicit
                                ? modeLabel(explicit.mode)
                                : block.origin}
                            </span>
                            {block.tier && (
                              <span className="rounded-full bg-slate-950 px-2 py-0.5 text-[10px] uppercase text-slate-500">
                                {block.tier}
                              </span>
                            )}
                          </div>
                          <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-400">
                            {block.content}
                          </p>
                          <div className="mt-2 flex flex-wrap items-center gap-2 font-mono text-[11px] text-slate-500">
                            <span>{block.source_id}</span>
                            <span>{block.token_count} tok</span>
                            <span>
                              pos {explicit?.position ?? block.position}
                            </span>
                          </div>
                        </div>
                        <div className="flex items-start gap-2">
                          <button
                            type="button"
                            title="Exclude"
                            className="icon-button h-9 w-9"
                            onClick={() =>
                              upsertOverride(
                                block.source_type,
                                block.source_id,
                                'exclude',
                                block.position,
                              )
                            }
                          >
                            <MinusCircle className="h-4 w-4" />
                          </button>
                          {explicit && (
                            <button
                              type="button"
                              title="Remove override"
                              className="icon-button h-9 w-9"
                              onClick={() =>
                                removeOverride(
                                  block.source_type,
                                  block.source_id,
                                )
                              }
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </section>

              <section className="space-y-5">
                <div className="panel-surface animate-fade-up stagger-3">
                  <div className="flex items-center justify-between border-b border-slate-800/70 px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Save className="h-4 w-4 text-emerald-300" />
                      <h2 className="text-sm font-semibold text-slate-100">
                        Override Layer
                      </h2>
                    </div>
                    <span className="text-xs text-slate-500">
                      {saveMutation.isPending ? 'saving' : 'saved'}
                    </span>
                  </div>
                  <div className="divide-y divide-slate-800/70">
                    {draftOverrides.length === 0 ? (
                      <div className="px-4 py-6 text-sm text-slate-500">
                        No manual overrides.
                      </div>
                    ) : (
                      draftOverrides.map((item) => (
                        <div
                          key={overrideKey(item.source_type, item.source_id)}
                          className="flex items-center gap-3 px-4 py-3"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-medium text-slate-100">
                                {item.source_type}
                              </span>
                              <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] uppercase text-slate-400">
                                {modeLabel(item.mode)}
                              </span>
                              <span className="text-xs text-slate-500">
                                pos {item.position}
                              </span>
                            </div>
                            <code className="mt-1 block truncate text-xs text-slate-500">
                              {item.source_id}
                            </code>
                          </div>
                          <button
                            type="button"
                            title="Remove override"
                            className="icon-button h-9 w-9"
                            onClick={() =>
                              removeOverride(item.source_type, item.source_id)
                            }
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                <div className="panel-surface animate-fade-up stagger-4">
                  <div className="flex items-center justify-between border-b border-slate-800/70 px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Eye className="h-4 w-4 text-sky-300" />
                      <h2 className="text-sm font-semibold text-slate-100">
                        Rendered
                      </h2>
                    </div>
                    <span className="text-xs text-slate-500">
                      {preview?.total_tokens ?? 0} tokens
                    </span>
                  </div>
                  <pre className="max-h-[42rem] overflow-auto whitespace-pre-wrap px-4 py-4 font-mono text-xs leading-5 text-slate-300">
                    {preview?.rendered || 'No context rendered.'}
                  </pre>
                </div>
              </section>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
