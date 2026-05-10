'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, Pencil, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useToast } from '@/components/error/toast'
import { type Prompt, updatePrompt } from '@/lib/api/prompts'
import { cn } from '@/lib/utils'

interface Props {
  prompt: Prompt
  onClose: () => void
  onSaved: () => void
}

export function EditPromptModal({ prompt, onClose, onSaved }: Props) {
  const { addToast } = useToast()
  const queryClient = useQueryClient()
  const [name, setName] = useState(prompt.name)
  const [description, setDescription] = useState(prompt.description ?? '')
  const [content, setContent] = useState(prompt.content)

  useEffect(() => {
    setName(prompt.name)
    setDescription(prompt.description ?? '')
    setContent(prompt.content)
  }, [prompt])

  const saveMutation = useMutation({
    mutationFn: () =>
      updatePrompt(prompt.slug, {
        name,
        content,
        description: description || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompts'] })
      queryClient.invalidateQueries({ queryKey: ['prompt', prompt.slug] })
      queryClient.invalidateQueries({
        queryKey: ['runtime-context', 'preview'],
      })
      onSaved()
      onClose()
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: 'Save failed',
        message: err instanceof Error ? err.message : 'Unknown error',
      })
    },
  })

  const hasChanges =
    name !== prompt.name ||
    description !== (prompt.description ?? '') ||
    content !== prompt.content
  const canSave =
    hasChanges && content.trim().length > 0 && name.trim().length > 0

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      data-testid="edit-prompt-modal"
    >
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative w-full max-w-3xl mx-4 rounded-xl bg-slate-900 shadow-2xl border border-slate-800">
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-full bg-violet-900/30">
              <Pencil className="w-5 h-5 text-violet-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-100">
                Edit Prompt
              </h2>
              <p className="text-xs text-slate-400 font-mono">{prompt.slug}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={saveMutation.isPending}
            aria-label="Close dialog"
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 disabled:opacity-50 cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          <label className="block">
            <span className="block text-xs font-medium text-slate-300 mb-1">
              Name
            </span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={saveMutation.isPending}
              className="w-full px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sm text-slate-100 focus:border-violet-500 focus:outline-none disabled:opacity-50"
            />
          </label>

          <label className="block">
            <span className="block text-xs font-medium text-slate-300 mb-1">
              Description <span className="text-slate-500">(optional)</span>
            </span>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={saveMutation.isPending}
              className="w-full px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sm text-slate-100 focus:border-violet-500 focus:outline-none disabled:opacity-50"
            />
          </label>

          <label className="block">
            <span className="block text-xs font-medium text-slate-300 mb-1">
              Content
            </span>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              disabled={saveMutation.isPending}
              rows={14}
              className="w-full px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sm text-slate-100 font-mono focus:border-violet-500 focus:outline-none disabled:opacity-50"
            />
          </label>

          <div className="p-3 rounded-lg bg-slate-800/40 border border-slate-700 text-xs text-slate-400">
            For agent assignments, scope flags, and revision history, use the
            full prompt page.
          </div>
        </div>

        <div className="flex items-center justify-between p-4 border-t border-slate-800 bg-slate-800/30">
          <div className="text-xs text-slate-500">
            {hasChanges ? (
              <span className="text-violet-400">Unsaved changes</span>
            ) : (
              'No changes'
            )}
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              disabled={saveMutation.isPending}
              className="px-4 py-2 rounded-lg text-sm font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => saveMutation.mutate()}
              disabled={!canSave || saveMutation.isPending}
              className={cn(
                'px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors flex items-center gap-2',
                'bg-violet-600 hover:bg-violet-700',
                'disabled:opacity-50 disabled:cursor-not-allowed',
              )}
            >
              {saveMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Saving...
                </>
              ) : (
                'Save Changes'
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
