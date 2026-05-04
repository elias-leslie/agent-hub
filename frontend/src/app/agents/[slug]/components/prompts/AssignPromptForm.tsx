'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus } from 'lucide-react'
import { useState } from 'react'

import {
  type AgentPromptAssignment,
  assignPrompt,
  type Prompt,
} from '@/lib/api/prompts'

interface AssignPromptFormProps {
  agentSlug: string
  availablePrompts: Prompt[]
  orderedAssignments: AgentPromptAssignment[]
  onClose: () => void
}

export function AssignPromptForm({
  agentSlug,
  availablePrompts,
  orderedAssignments,
  onClose,
}: AssignPromptFormProps) {
  const queryClient = useQueryClient()
  const [selectedPromptSlug, setSelectedPromptSlug] = useState('')
  const [assignRole, setAssignRole] = useState('context')

  const assignMutation = useMutation({
    mutationFn: async (payload: {
      prompt_slug: string
      role: string
      priority: number
    }) => assignPrompt(agentSlug, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent-prompts', agentSlug] })
      setSelectedPromptSlug('')
      setAssignRole('context')
      onClose()
    },
  })

  return (
    <div className="space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-100">
        Assign Existing Prompt
      </h3>
      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-1.5">
          <span className="text-xs font-medium text-slate-400">Prompt</span>
          <select
            value={selectedPromptSlug}
            onChange={(event) => setSelectedPromptSlug(event.target.value)}
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none transition"
          >
            <option value="">Select a prompt...</option>
            {availablePrompts.map((prompt) => (
              <option key={prompt.slug} value={prompt.slug}>
                {prompt.name}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1.5">
          <span className="text-xs font-medium text-slate-400">Role</span>
          <input
            value={assignRole}
            onChange={(event) => setAssignRole(event.target.value)}
            list="prompt-role-options"
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none transition"
          />
        </label>
      </div>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm font-medium text-slate-200 transition hover:bg-slate-800 cursor-pointer"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() =>
            assignMutation.mutate({
              prompt_slug: selectedPromptSlug,
              role: assignRole,
              priority:
                orderedAssignments.length === 0
                  ? 0
                  : orderedAssignments[orderedAssignments.length - 1].priority +
                    10,
            })
          }
          disabled={
            !selectedPromptSlug || !assignRole || assignMutation.isPending
          }
          className="inline-flex items-center gap-2 rounded-lg bg-amber-500 px-3 py-2 text-sm font-semibold text-slate-950 transition hover:bg-amber-400 disabled:opacity-50"
        >
          {assignMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Plus className="h-4 w-4" />
          )}
          Assign Prompt
        </button>
      </div>
    </div>
  )
}
