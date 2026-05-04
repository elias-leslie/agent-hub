'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  GripVertical,
  Loader2,
  Trash2,
  Unplug,
} from 'lucide-react'
import { useEffect, useState } from 'react'

import {
  type AgentPromptAssignment,
  deletePrompt,
  removeAssignment,
  updateAssignment,
  updatePrompt,
} from '@/lib/api/prompts'

interface PromptAssignmentCardProps {
  agentSlug: string
  assignment: AgentPromptAssignment
  onPromptUpdated: () => void
  onPromptDeleted: (slug: string) => void
  onAssignmentRemoved: (slug: string) => void
  draggable?: boolean
  onDragStart?: (slug: string) => void
  onDragOver?: (slug: string) => void
  onDrop?: (slug: string) => void
}

export function PromptAssignmentCard({
  agentSlug,
  assignment,
  onPromptUpdated,
  onPromptDeleted,
  onAssignmentRemoved,
  draggable = false,
  onDragStart,
  onDragOver,
  onDrop,
}: PromptAssignmentCardProps) {
  const prompt = assignment.prompt
  const ownedByCurrentAgent = prompt.owner_agent_slug === agentSlug
  const canDeletePrompt = ownedByCurrentAgent && !prompt.deletion_locked
  const canRemoveAssignment = !ownedByCurrentAgent
  const [expanded, setExpanded] = useState(false)
  const [name, setName] = useState(prompt.name)
  const [description, setDescription] = useState(prompt.description ?? '')
  const [content, setContent] = useState(prompt.content)
  const [enabled, setEnabled] = useState(prompt.enabled)
  const [role, setRole] = useState(assignment.role)

  useEffect(() => {
    setName(prompt.name)
    setDescription(prompt.description ?? '')
    setContent(prompt.content)
    setEnabled(prompt.enabled)
    setRole(assignment.role)
  }, [
    assignment.role,
    prompt.content,
    prompt.description,
    prompt.enabled,
    prompt.name,
  ])

  const queryClient = useQueryClient()
  const saveMutation = useMutation({
    mutationFn: async () => {
      const promptChanged =
        name !== prompt.name ||
        description !== (prompt.description ?? '') ||
        content !== prompt.content ||
        enabled !== prompt.enabled
      const assignmentChanged = role !== assignment.role

      if (promptChanged) {
        await updatePrompt(prompt.slug, {
          name,
          description: description || undefined,
          content,
          enabled,
        })
      }
      if (assignmentChanged) {
        await updateAssignment(agentSlug, prompt.slug, { role })
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent-prompts', agentSlug] })
      queryClient.invalidateQueries({ queryKey: ['prompts'] })
      onPromptUpdated()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async () => deletePrompt(prompt.slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent-prompts', agentSlug] })
      queryClient.invalidateQueries({ queryKey: ['prompts'] })
      onPromptDeleted(prompt.slug)
    },
  })

  const removeMutation = useMutation({
    mutationFn: async () => removeAssignment(agentSlug, prompt.slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent-prompts', agentSlug] })
      onAssignmentRemoved(prompt.slug)
    },
  })

  const dirty =
    name !== prompt.name ||
    description !== (prompt.description ?? '') ||
    content !== prompt.content ||
    enabled !== prompt.enabled ||
    role !== assignment.role

  return (
    <div
      draggable={draggable}
      onDragStart={() => onDragStart?.(prompt.slug)}
      onDragOver={(event) => {
        if (!draggable) return
        event.preventDefault()
        onDragOver?.(prompt.slug)
      }}
      onDrop={() => onDrop?.(prompt.slug)}
      className="rounded-xl border border-slate-800 bg-slate-900"
    >
      <div className="flex items-center gap-2 px-4 py-3">
        {draggable ? (
          <span className="text-slate-400">
            <GripVertical className="h-4 w-4" />
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-slate-500" />
          ) : (
            <ChevronRight className="h-4 w-4 text-slate-500" />
          )}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="truncate text-sm font-medium text-slate-100">
                {prompt.name}
              </span>
              <span className="rounded-full bg-blue-900/30 px-2 py-0.5 text-[10px] font-semibold text-amber-300">
                {assignment.role}
              </span>
              <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] font-semibold text-slate-300">
                p{assignment.priority}
              </span>
              <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] font-semibold text-slate-300">
                {prompt.prompt_type}
              </span>
              {prompt.deletion_locked ? (
                <span className="rounded-full bg-amber-900/30 px-2 py-0.5 text-[10px] font-semibold text-amber-300">
                  locked
                </span>
              ) : null}
              {ownedByCurrentAgent ? (
                <span className="rounded-full bg-emerald-900/30 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                  owned
                </span>
              ) : null}
            </div>
            <p className="truncate text-xs text-slate-400">{prompt.slug}</p>
          </div>
        </button>
      </div>

      {expanded ? (
        <div className="space-y-4 border-t border-slate-800 px-4 py-4">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-slate-400">Name</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none transition"
              />
            </label>
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-slate-400">Role</span>
              <input
                value={role}
                onChange={(event) => setRole(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none transition"
              />
            </label>
          </div>

          <label className="space-y-1.5">
            <span className="text-xs font-medium text-slate-400">
              Description
            </span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={2}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none transition"
            />
          </label>

          <label className="space-y-1.5">
            <span className="text-xs font-medium text-slate-400">Content</span>
            <textarea
              value={content}
              onChange={(event) => setContent(event.target.value)}
              rows={16}
              className="min-h-[260px] w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs outline-none transition"
            />
          </label>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <label className="inline-flex items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
              />
              Enabled
            </label>
            <div className="flex flex-wrap items-center gap-2">
              {canRemoveAssignment ? (
                <button
                  type="button"
                  onClick={() => removeMutation.mutate()}
                  disabled={removeMutation.isPending}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-2 text-xs font-medium text-slate-300 transition hover:bg-slate-800 disabled:opacity-50"
                >
                  <Unplug className="h-3.5 w-3.5" />
                  Remove Assignment
                </button>
              ) : null}
              {canDeletePrompt ? (
                <button
                  type="button"
                  onClick={() => deleteMutation.mutate()}
                  disabled={deleteMutation.isPending}
                  className="inline-flex items-center gap-1 rounded-lg border border-rose-900/60 px-3 py-2 text-xs font-medium text-rose-300 transition hover:bg-rose-950/30 disabled:opacity-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Delete Prompt
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => saveMutation.mutate()}
                disabled={!dirty || saveMutation.isPending}
                className="inline-flex items-center gap-1 rounded-lg bg-amber-500 px-3 py-2 text-xs font-semibold text-slate-950 transition hover:bg-amber-400 disabled:opacity-50"
              >
                {saveMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                )}
                Save
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
