'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Loader2, Plus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { fetchProjectConfigs } from '@/app/chat/hooks/useProjectContext'
import {
  type AgentPromptAssignment,
  fetchAgentPrompts,
  fetchOptionalPrompt,
  fetchPrompts,
  type Prompt,
  updateAssignment,
} from '@/lib/api/prompts'
import type {
  AgentPreview,
  PreviewProjectOption,
  PreviewScenario,
  PreviewTaskType,
} from '../types'
import { AgentPreviewPanel } from './AgentPreviewPanel'
import { AssignPromptForm } from './prompts/AssignPromptForm'
import { CreatePromptForm } from './prompts/CreatePromptForm'
import { LinkedPromptCard } from './prompts/LinkedPromptCard'
import { PromptAssignmentCard } from './prompts/PromptAssignmentCard'

interface PromptsTabProps {
  agentSlug: string
  preview?: AgentPreview
  previewFetching?: boolean
  previewError?: string | null
  showInlinePreview?: boolean
  setShowInlinePreview?: (show: boolean) => void
  previewMode?: PreviewTaskType
  setPreviewMode?: (mode: PreviewTaskType) => void
  previewScenario?: PreviewScenario
  onPreviewScenarioChange?: (updates: Partial<PreviewScenario>) => void
  refetchPreview?: () => void
}

const PERSONA_WORKFLOW_PROMPT_SLUGS = [
  'persona-focus-harness',
  'persona-heartbeat-orchestrator',
  'persona-wake-guidance',
  'persona-onboarding-bootstrap',
  'persona-onboarding-continuation',
  'persona-onboarding-pending-approval',
  'persona-onboarding-review',
  'persona-evolution-guidelines',
  'persona-improvement-review',
]

const DEFAULT_ROLES = ['system', 'autocode', 'context', 'guardrail']

export function PromptsTab({
  agentSlug,
  preview,
  previewFetching = false,
  previewError,
  showInlinePreview = false,
  setShowInlinePreview,
  previewMode = 'chat',
  setPreviewMode,
  previewScenario,
  onPreviewScenarioChange,
  refetchPreview,
}: PromptsTabProps) {
  const queryClient = useQueryClient()
  const [showAssignForm, setShowAssignForm] = useState(false)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [draggingSlug, setDraggingSlug] = useState<string | null>(null)

  const { data: assignments = [], isLoading: assignmentsLoading } = useQuery<
    AgentPromptAssignment[]
  >({
    queryKey: ['agent-prompts', agentSlug],
    queryFn: () => fetchAgentPrompts(agentSlug),
  })

  const { data: allPrompts = [] } = useQuery<Prompt[]>({
    queryKey: ['prompts'],
    queryFn: () => fetchPrompts(),
    enabled: showAssignForm,
  })

  const { data: personaWorkflowPrompts = [] } = useQuery<Prompt[]>({
    queryKey: ['persona-workflow-prompts'],
    enabled: agentSlug === 'persona',
    queryFn: async () => {
      const prompts = await Promise.all(
        PERSONA_WORKFLOW_PROMPT_SLUGS.map((slug) => fetchOptionalPrompt(slug)),
      )
      return prompts.filter((prompt): prompt is Prompt => prompt !== null)
    },
  })

  const { data: previewProjects = [] } = useQuery<PreviewProjectOption[]>({
    queryKey: ['project-configs'],
    queryFn: fetchProjectConfigs,
  })

  const assignedSlugs = useMemo(
    () => new Set(assignments.map((a) => a.prompt.slug)),
    [assignments],
  )

  const availablePrompts = useMemo(
    () => allPrompts.filter((p) => !assignedSlugs.has(p.slug)),
    [allPrompts, assignedSlugs],
  )

  const orderedAssignments = useMemo(
    () =>
      [...assignments].sort((left, right) => left.priority - right.priority),
    [assignments],
  )

  const reorderMutation = useMutation({
    mutationFn: async (nextAssignments: AgentPromptAssignment[]) => {
      await Promise.all(
        nextAssignments.map((assignment, index) =>
          updateAssignment(agentSlug, assignment.prompt.slug, {
            priority: index * 10,
          }),
        ),
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent-prompts', agentSlug] })
    },
  })

  const handleDrop = (targetSlug: string) => {
    if (!draggingSlug || draggingSlug === targetSlug) return
    const current = [...orderedAssignments]
    const fromIndex = current.findIndex((a) => a.prompt.slug === draggingSlug)
    const toIndex = current.findIndex((a) => a.prompt.slug === targetSlug)
    if (fromIndex < 0 || toIndex < 0) return
    const [moved] = current.splice(fromIndex, 1)
    current.splice(toIndex, 0, moved)
    setDraggingSlug(null)
    reorderMutation.mutate(current)
  }

  const canPreview = Boolean(
    setShowInlinePreview && setPreviewMode && refetchPreview,
  )

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">Prompts</h2>
          <p className="mt-1 text-sm text-slate-400">
            Edit assigned prompt documents inline and reorder runtime prompt
            assignments.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setShowCreateForm((v) => !v)
              setShowAssignForm(false)
            }}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm font-medium text-slate-200 transition hover:bg-slate-800 cursor-pointer"
          >
            <Plus className="h-4 w-4" />
            New Prompt
          </button>
          <button
            type="button"
            onClick={() => {
              setShowAssignForm((v) => !v)
              setShowCreateForm(false)
            }}
            className="inline-flex items-center gap-2 rounded-lg bg-amber-500 px-3 py-2 text-sm font-semibold text-slate-950 transition hover:bg-amber-400"
          >
            <Plus className="h-4 w-4" />
            Assign Existing
          </button>
        </div>
      </div>

      {showCreateForm ? (
        <CreatePromptForm
          agentSlug={agentSlug}
          orderedAssignments={orderedAssignments}
          onClose={() => setShowCreateForm(false)}
        />
      ) : null}

      {showAssignForm ? (
        <AssignPromptForm
          agentSlug={agentSlug}
          availablePrompts={availablePrompts}
          orderedAssignments={orderedAssignments}
          onClose={() => setShowAssignForm(false)}
        />
      ) : null}

      <datalist id="prompt-role-options">
        {DEFAULT_ROLES.map((role) => (
          <option key={role} value={role} />
        ))}
      </datalist>

      {canPreview ? (
        <AgentPreviewPanel
          preview={preview}
          previewFetching={previewFetching}
          previewError={previewError}
          previewMode={previewMode}
          onPreviewModeChange={(mode) => setPreviewMode?.(mode)}
          scenario={
            previewScenario ?? { projectId: '', phase: '', promptInput: '' }
          }
          onScenarioChange={(updates) => onPreviewScenarioChange?.(updates)}
          showPreview={showInlinePreview}
          onTogglePreview={() => setShowInlinePreview?.(!showInlinePreview)}
          onRefresh={() => refetchPreview?.()}
          projectOptions={previewProjects}
        />
      ) : null}

      <div className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-100">
            Prompt Assignments
          </h3>
          <p className="mt-1 text-xs text-slate-400">
            Drag to reorder the runtime prompt stack. Owned prompts stay under
            this agent; shared prompts can be detached.
          </p>
        </div>
        {assignmentsLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
          </div>
        ) : orderedAssignments.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-700 px-6 py-12 text-center text-slate-400">
            <FileText className="mx-auto mb-3 h-8 w-8 opacity-50" />
            No prompts assigned yet.
          </div>
        ) : (
          <div className="space-y-3">
            {orderedAssignments.map((assignment) => (
              <PromptAssignmentCard
                key={assignment.prompt.slug}
                agentSlug={agentSlug}
                assignment={assignment}
                draggable={reorderMutation.isPending === false}
                onDragStart={setDraggingSlug}
                onDragOver={() => undefined}
                onDrop={handleDrop}
                onPromptUpdated={() => undefined}
                onPromptDeleted={() => undefined}
                onAssignmentRemoved={() => undefined}
              />
            ))}
          </div>
        )}
      </div>

      {agentSlug === 'persona' && personaWorkflowPrompts.length > 0 ? (
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-100">
              Workflow Prompt Docs
            </h3>
            <p className="mt-1 text-xs text-slate-400">
              Persona-specific workflow prompts that are used outside the
              ordered system prompt stack.
            </p>
          </div>
          <div className="space-y-3">
            {personaWorkflowPrompts.map((prompt) => (
              <LinkedPromptCard
                key={prompt.slug}
                prompt={prompt}
                onUpdated={() => undefined}
              />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
