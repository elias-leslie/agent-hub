'use client'

import { CheckCircle2, History, Loader2, RotateCcw } from 'lucide-react'
import { useState } from 'react'

import type { Prompt, PromptRevision } from '@/lib/api/prompts'
import { cn } from '@/lib/utils'

interface PromptRevisionHistoryProps {
  prompt: Prompt
  revisions: PromptRevision[]
  isLoading: boolean
  restoringRevisionId: string | null
  onRestore: (revisionId: string) => void
}

const ACTION_STYLES: Record<string, string> = {
  create: 'bg-emerald-950/30 text-emerald-300 border-emerald-900',
  update: 'bg-blue-950/30 text-amber-300 border-blue-900',
  restore: 'bg-amber-950/30 text-amber-300 border-amber-900',
  delete: 'bg-rose-950/30 text-rose-300 border-rose-900',
}

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function shortenHash(hash: string): string {
  return hash.slice(0, 10)
}

function arraysEqual(left: string[], right: string[]): boolean {
  if (left.length !== right.length) {
    return false
  }

  return left.every((value, index) => value === right[index])
}

export function PromptRevisionHistory({
  prompt,
  revisions,
  isLoading,
  restoringRevisionId,
  onRestore,
}: PromptRevisionHistoryProps) {
  const [pendingRestoreId, setPendingRestoreId] = useState<string | null>(null)
  const currentRevisionId =
    revisions.find((revision) => {
      return (
        revision.content === prompt.content &&
        revision.description === prompt.description &&
        revision.enabled === prompt.enabled &&
        revision.is_global === prompt.is_global &&
        arraysEqual(revision.exclude_agents, prompt.exclude_agents)
      )
    })?.id ?? null

  return (
    <section className="panel-surface animate-fade-up stagger-3 p-5 lg:p-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-slate-100">
            <History className="h-4 w-4" />
            <h2 className="text-sm font-semibold">Revision History</h2>
          </div>
          <p className="mt-1 text-xs text-slate-400">
            Immutable prompt snapshots for rollback and benchmark attribution.
          </p>
        </div>
        <div className="page-pill">{revisions.length} revisions</div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12 text-slate-400">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : revisions.length === 0 ? (
        <div className="mt-4 rounded-2xl border border-dashed border-slate-700/80 bg-slate-950/55 px-4 py-8 text-center text-sm text-slate-400">
          No revisions recorded yet.
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          {revisions.map((revision) => {
            const isCurrent = revision.id === currentRevisionId
            const isPending = pendingRestoreId === revision.id
            const isRestoring = restoringRevisionId === revision.id

            return (
              <article
                key={revision.id}
                className="rounded-2xl border border-slate-800/80 bg-slate-950/45 px-4 py-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cn(
                          'rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide',
                          ACTION_STYLES[revision.action] ??
                            'bg-slate-800 text-slate-300 border-slate-700',
                        )}
                      >
                        {revision.action}
                      </span>
                      {isCurrent && (
                        <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-semibold text-emerald-100">
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          Current state
                        </span>
                      )}
                    </div>
                    <div className="text-sm text-slate-100">
                      <span className="font-medium">
                        {revision.prompt_name}
                      </span>
                      <span className="ml-2 text-slate-400">
                        {formatTimestamp(revision.created_at)}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
                      <span>Changed by {revision.changed_by ?? 'system'}</span>
                      <span>Hash {shortenHash(revision.content_hash)}</span>
                      <span>{revision.enabled ? 'Enabled' : 'Disabled'}</span>
                      <span>
                        {revision.is_global ? 'Global' : 'Non-global'}
                      </span>
                    </div>
                    {revision.change_reason && (
                      <p className="text-sm text-slate-300">
                        {revision.change_reason}
                      </p>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => {
                      if (isPending) {
                        onRestore(revision.id)
                        setPendingRestoreId(null)
                        return
                      }
                      setPendingRestoreId(revision.id)
                    }}
                    disabled={isRestoring}
                    className={cn(
                      'inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium transition-colors',
                      isPending
                        ? 'border-amber-500/20 bg-amber-500/10 text-amber-100'
                        : 'border-slate-700/80 bg-slate-900/80 text-slate-300 hover:border-slate-600 hover:bg-slate-800/90',
                    )}
                  >
                    {isRestoring ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <RotateCcw className="h-4 w-4" />
                    )}
                    {isPending ? 'Confirm Restore' : 'Restore'}
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
