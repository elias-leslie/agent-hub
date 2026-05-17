'use client'

import { DndContext, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { EditEpisodeModal } from '@/components/memory/EditEpisodeModal'
import { BootReactorTopbar } from '@/components/runtime-context/BootReactorTopbar'
import { EditPromptModal } from '@/components/runtime-context/EditPromptModal'
import { LibraryPane } from '@/components/runtime-context/LibraryPane'
import { RenderedPane } from '@/components/runtime-context/RenderedPane'
import styles from '@/components/runtime-context/runtime-context.module.css'
import { useRuntimeContext } from '@/components/runtime-context/useRuntimeContext'
import { fetchProjectRoots } from '@/lib/api/project-permissions'
import type { RuntimeContextBlock } from '@/lib/api/runtime-context'

type EditTarget =
  | { kind: 'memory'; uuid: string }
  | { kind: 'prompt'; slug: string }
  | null

export default function RuntimeContextPage() {
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    null,
  )
  const ctx = useRuntimeContext(undefined, selectedProjectId)
  const projectsQuery = useQuery({
    queryKey: ['runtime-context', 'projects'],
    queryFn: fetchProjectRoots,
    staleTime: 5 * 60 * 1000,
  })
  const projectOptions = useMemo(() => {
    const data = projectsQuery.data ?? {}
    return Object.keys(data)
      .sort()
      .map((id) => ({ id, label: id }))
  }, [projectsQuery.data])
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  )
  const [editTarget, setEditTarget] = useState<EditTarget>(null)

  const isCrossPaneDragging = typeof ctx.activeDragId === 'string'

  const onEditBlock = (block: RuntimeContextBlock) => {
    setEditTarget(
      block.source_type === 'memory'
        ? { kind: 'memory', uuid: block.source_id }
        : { kind: 'prompt', slug: block.source_id },
    )
  }
  const closeEdit = () => setEditTarget(null)

  const editingEpisode =
    editTarget?.kind === 'memory'
      ? ctx.episodes.find((episode) => episode.uuid === editTarget.uuid)
      : null
  const editingPrompt =
    editTarget?.kind === 'prompt'
      ? ctx.prompts.find((prompt) => prompt.slug === editTarget.slug)
      : null

  return (
    <DndContext
      sensors={sensors}
      onDragStart={ctx.onDragStart}
      onDragEnd={ctx.onDragEnd}
      onDragCancel={() => ctx.onDragEnd({} as never)}
    >
      <div className={styles.shell}>
        <BootReactorTopbar
          used={ctx.preview?.total_tokens ?? 0}
          budget={ctx.preview?.budget_tokens ?? 0}
          budgetEnabled={ctx.preview?.budget_enabled ?? false}
          onRefresh={ctx.onRefresh}
          onReset={ctx.onResetOverrides}
          refreshing={ctx.isLoading}
          resetting={ctx.saving}
          hasOverrides={ctx.draftOverrides.length > 0}
          profile={ctx.profile}
          projects={projectOptions}
          selectedProjectId={selectedProjectId}
          onProjectChange={setSelectedProjectId}
        />

        {ctx.isLoading ? (
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
          </div>
        ) : (
          <div className={styles.grid}>
            <RenderedPane
              blocks={ctx.blocks}
              excluded={ctx.excludedBlocks}
              saving={ctx.saving}
              fullContentLookup={ctx.fullContentLookup}
              rendered={ctx.preview?.rendered ?? ''}
              projectIndex={ctx.preview?.project_index ?? ''}
              toolCapabilities={ctx.preview?.tool_capabilities ?? ''}
              totalTokens={ctx.preview?.total_tokens ?? 0}
              budgetTokens={ctx.preview?.budget_tokens ?? 0}
              budgetEnabled={ctx.preview?.budget_enabled ?? false}
              onExclude={ctx.onExclude}
              onRestore={ctx.onRestore}
              onEdit={onEditBlock}
              onRenderModeChange={ctx.onRenderModeChange}
              onRemoveDefault={ctx.onRemoveDefault}
              isCrossPaneDragging={isCrossPaneDragging}
            />
            <LibraryPane
              library={ctx.library}
              inContextKeys={ctx.inContextKeys}
              onPin={ctx.onPin}
              onEdit={onEditBlock}
              onMakeDefault={ctx.onMakeDefault}
              isCrossPaneDragging={isCrossPaneDragging}
              totalCount={ctx.totalCount}
            />
          </div>
        )}
      </div>
      {editingEpisode ? (
        <EditEpisodeModal
          episode={editingEpisode}
          isOpen
          onClose={closeEdit}
          onSaved={() => {
            ctx.onRefresh()
            closeEdit()
          }}
        />
      ) : null}
      {editingPrompt ? (
        <EditPromptModal
          prompt={editingPrompt}
          onClose={closeEdit}
          onSaved={ctx.onRefresh}
        />
      ) : null}
    </DndContext>
  )
}
