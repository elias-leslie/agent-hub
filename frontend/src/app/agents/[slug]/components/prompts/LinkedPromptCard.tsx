'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ChevronDown, ChevronRight, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { CompactnessMeter } from '@/components/CompactnessMeter'
import { type Prompt, updatePrompt } from '@/lib/api/prompts'

interface LinkedPromptCardProps {
  prompt: Prompt
  onUpdated: () => void
}

export function LinkedPromptCard({ prompt, onUpdated }: LinkedPromptCardProps) {
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const [name, setName] = useState(prompt.name)
  const [description, setDescription] = useState(prompt.description ?? '')
  const [content, setContent] = useState(prompt.content)
  const [enabled, setEnabled] = useState(prompt.enabled)

  useEffect(() => {
    setName(prompt.name)
    setDescription(prompt.description ?? '')
    setContent(prompt.content)
    setEnabled(prompt.enabled)
  }, [prompt.content, prompt.description, prompt.enabled, prompt.name])

  const saveMutation = useMutation({
    mutationFn: async () =>
      updatePrompt(prompt.slug, {
        name,
        description: description || undefined,
        content,
        enabled,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompt', prompt.slug] })
      queryClient.invalidateQueries({ queryKey: ['persona-workflow-prompts'] })
      queryClient.invalidateQueries({ queryKey: ['prompts'] })
      onUpdated()
    },
  })

  const dirty =
    name !== prompt.name ||
    description !== (prompt.description ?? '') ||
    content !== prompt.content ||
    enabled !== prompt.enabled

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left"
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
            <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] font-semibold text-slate-300">
              linked
            </span>
          </div>
          <p className="truncate text-xs text-slate-400">{prompt.slug}</p>
        </div>
      </button>
      {expanded ? (
        <div className="space-y-4 border-t border-slate-800 px-4 py-4">
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-slate-400">Name</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none transition"
            />
          </label>
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
              rows={14}
              className="min-h-[220px] w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs outline-none transition"
            />
            <CompactnessMeter content={content} kind="prompt" />
          </label>
          <div className="flex items-center justify-between gap-3">
            <label className="inline-flex items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
              />
              Enabled
            </label>
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
      ) : null}
    </div>
  )
}
