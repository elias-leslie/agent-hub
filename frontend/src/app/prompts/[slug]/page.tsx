'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Globe,
  Loader2,
  Save,
  Trash2,
} from 'lucide-react'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { PromptRevisionHistory } from '@/app/prompts/[slug]/components/PromptRevisionHistory'
import { CompactnessMeter } from '@/components/CompactnessMeter'
import {
  deletePrompt,
  fetchPrompt,
  fetchPromptRevisions,
  restorePromptRevision,
  updatePrompt,
} from '@/lib/api/prompts'
import { cn } from '@/lib/utils'

export default function PromptEditPage() {
  const params = useParams()
  const router = useRouter()
  const queryClient = useQueryClient()
  const slug = params.slug as string

  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [description, setDescription] = useState('')
  const [isGlobal, setIsGlobal] = useState(false)
  const [enabled, setEnabled] = useState(true)
  const [excludeAgents, setExcludeAgents] = useState<string[]>([])
  const [excludeInput, setExcludeInput] = useState('')
  const [changeReason, setChangeReason] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)

  const {
    data: prompt,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['prompt', slug],
    queryFn: () => fetchPrompt(slug),
    enabled: !!slug,
  })

  const { data: revisions = [], isLoading: revisionsLoading } = useQuery({
    queryKey: ['prompt-revisions', slug],
    queryFn: () => fetchPromptRevisions(slug),
    enabled: !!slug,
  })

  useEffect(() => {
    if (prompt) {
      setName(prompt.name)
      setContent(prompt.content)
      setDescription(prompt.description ?? '')
      setIsGlobal(prompt.is_global)
      setEnabled(prompt.enabled)
      setExcludeAgents(prompt.exclude_agents ?? [])
    }
  }, [prompt])

  const saveMutation = useMutation({
    mutationFn: () =>
      updatePrompt(slug, {
        name,
        content,
        description: description || undefined,
        is_global: isGlobal,
        enabled,
        exclude_agents: excludeAgents,
        change_reason: changeReason || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompt', slug] })
      queryClient.invalidateQueries({ queryKey: ['prompt-revisions', slug] })
      queryClient.invalidateQueries({ queryKey: ['prompts'] })
      setChangeReason('')
    },
  })

  const restoreMutation = useMutation({
    mutationFn: (revisionId: string) =>
      restorePromptRevision(
        slug,
        revisionId,
        changeReason || `Restore ${slug} revision`,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompt', slug] })
      queryClient.invalidateQueries({ queryKey: ['prompt-revisions', slug] })
      queryClient.invalidateQueries({ queryKey: ['prompts'] })
      setChangeReason('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deletePrompt(slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompts'] })
      router.push('/prompts')
    },
  })

  const handleDelete = () => {
    if (confirmDelete) {
      deleteMutation.mutate()
    } else {
      setConfirmDelete(true)
    }
  }

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    )
  }

  if (error || !prompt) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <AlertCircle className="h-10 w-10 text-red-500 mx-auto mb-3" />
          <p className="text-sm text-slate-400">Prompt not found</p>
          <button
            onClick={() => router.push('/prompts')}
            className="mt-4 px-4 py-2 text-sm font-medium text-amber-500 hover:underline"
          >
            Back to Prompts
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="page-shell">
      <div className="page-backdrop" />
      {/* Toast notifications */}
      {saveMutation.isSuccess && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-950/40 border border-emerald-800 text-emerald-400 text-sm shadow-lg">
          <CheckCircle2 className="h-4 w-4" />
          Prompt saved successfully
        </div>
      )}
      {saveMutation.isError && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-2 px-4 py-2 rounded-lg bg-red-950/40 border border-red-800 text-red-400 text-sm shadow-lg">
          <AlertCircle className="h-4 w-4" />
          Failed to save prompt
        </div>
      )}
      {deleteMutation.isError && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-2 px-4 py-2 rounded-lg bg-red-950/40 border border-red-800 text-red-400 text-sm shadow-lg">
          <AlertCircle className="h-4 w-4" />
          Failed to delete prompt
        </div>
      )}

      <header className="page-header">
        <div className="page-container px-4 lg:px-8">
          <div className="page-header-row">
            <div className="page-title-group">
              <button
                onClick={() => router.push('/prompts')}
                className="icon-button"
                aria-label="Go back"
              >
                <ArrowLeft className="h-5 w-5" />
              </button>
              <div className="page-title-icon">
                <Globe className="h-5 w-5" />
              </div>
              <div className="page-title-stack">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="page-title">{prompt.name}</h1>
                  <span className="page-pill font-mono">{prompt.slug}</span>
                </div>
                <div className="page-meta">
                  <span
                    className={cn(
                      'page-pill',
                      prompt.enabled
                        ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200'
                        : 'border-rose-500/20 bg-rose-500/10 text-rose-200',
                    )}
                  >
                    {prompt.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                  <span
                    className={cn(
                      'page-pill',
                      prompt.is_global
                        ? 'border-amber-500/20 bg-amber-500/10 text-amber-100'
                        : 'border-slate-700/80 bg-slate-900/90 text-slate-400',
                    )}
                  >
                    {prompt.is_global ? 'Global prompt' : 'Scoped prompt'}
                  </span>
                  {prompt.owner_agent_slug ? (
                    <span className="page-pill">
                      Owner {prompt.owner_agent_slug}
                    </span>
                  ) : null}
                </div>
              </div>
            </div>
            <div className="page-toolbar">
              <button
                type="button"
                onClick={handleDelete}
                disabled={deleteMutation.isPending || prompt.deletion_locked}
                className="inline-flex items-center gap-2 rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-2.5 text-sm font-medium text-rose-200 transition hover:bg-rose-500/15 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {deleteMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <span className="flex items-center gap-2">
                    <Trash2 className="h-4 w-4" />
                    {prompt.deletion_locked
                      ? 'Locked'
                      : confirmDelete
                        ? 'Confirm Delete'
                        : 'Delete'}
                  </span>
                )}
              </button>
              <button
                type="button"
                onClick={() => saveMutation.mutate()}
                disabled={saveMutation.isPending}
                className="button-primary disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-slate-800 disabled:text-slate-500 disabled:shadow-none"
              >
                {saveMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <span className="flex items-center gap-2">
                    <Save className="h-4 w-4" />
                    Save
                  </span>
                )}
              </button>
            </div>
          </div>
        </div>
      </header>

      <div className="page-container">
        <div className="page-frame">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_22rem]">
            <section className="panel-surface animate-fade-up">
              <div className="border-b border-slate-800/80 px-5 py-5 lg:px-6">
                <p className="section-kicker">Prompt Document</p>
                <h2 className="section-heading mt-2">Source Content</h2>
                <p className="section-copy mt-2 max-w-3xl">
                  Edit the prompt body, operator-facing description, and change
                  reason that downstream benchmark runs use for attribution.
                </p>
              </div>
              <div className="space-y-5 px-5 py-5 lg:px-6 lg:py-6">
                <div className="space-y-1.5">
                  <label className="detail-label">Name</label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="control-input"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="detail-label">Content</label>
                  <textarea
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    className="control-input min-h-[26rem] resize-y font-mono text-[13px] leading-6"
                  />
                  <CompactnessMeter content={content} kind="prompt" />
                </div>

                <div className="grid gap-5 lg:grid-cols-2">
                  <div className="space-y-1.5">
                    <label className="detail-label">Description</label>
                    <textarea
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      rows={5}
                      className="control-input min-h-36 resize-y"
                    />
                  </div>

                  <div className="section-card space-y-3">
                    <div>
                      <p className="detail-label">Change Reason</p>
                      <p className="mt-2 text-sm text-slate-400">
                        Saved with every update and restore so regressions can
                        be tied to a concrete prompt change.
                      </p>
                    </div>
                    <input
                      type="text"
                      value={changeReason}
                      onChange={(e) => setChangeReason(e.target.value)}
                      placeholder="Why are you changing this prompt?"
                      className="control-input"
                    />
                  </div>
                </div>
              </div>
            </section>

            <aside className="space-y-6">
              <section className="panel-surface animate-fade-up stagger-1 p-5 lg:p-6">
                <div className="section-header gap-4">
                  <div>
                    <p className="section-kicker">Prompt Identity</p>
                    <h2 className="section-heading mt-2">Overview</h2>
                  </div>
                </div>
                <div className="mt-5 space-y-3">
                  <div className="detail-card">
                    <p className="detail-label">Slug</p>
                    <p className="detail-value font-mono">{prompt.slug}</p>
                  </div>
                  <div className="detail-card">
                    <p className="detail-label">Ownership</p>
                    <p className="detail-value">
                      {prompt.owner_agent_slug
                        ? `Owned by ${prompt.owner_agent_slug}`
                        : 'Shared system prompt'}
                    </p>
                  </div>
                  {prompt.deletion_locked && (
                    <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
                      This prompt is locked and cannot be deleted.
                    </div>
                  )}
                </div>
              </section>

              <section className="panel-surface animate-fade-up stagger-2 p-5 lg:p-6">
                <p className="section-kicker">Distribution</p>
                <h2 className="section-heading mt-2">Scope & Status</h2>
                <div className="mt-5 space-y-4">
                  <div className="segmented-control">
                    <button
                      type="button"
                      onClick={() => setIsGlobal(true)}
                      className={cn(
                        'segmented-option',
                        isGlobal
                          ? 'border-amber-500/20 bg-amber-500/12 text-amber-100'
                          : 'hover:border-slate-700/80 hover:bg-slate-900/80 hover:text-slate-200',
                      )}
                    >
                      <Globe className="h-4 w-4" />
                      Global
                    </button>
                    <button
                      type="button"
                      onClick={() => setIsGlobal(false)}
                      className={cn(
                        'segmented-option',
                        !isGlobal
                          ? 'border-slate-600 bg-slate-900/90 text-slate-100'
                          : 'hover:border-slate-700/80 hover:bg-slate-900/80 hover:text-slate-200',
                      )}
                    >
                      Scoped
                    </button>
                    <button
                      type="button"
                      onClick={() => setEnabled(!enabled)}
                      className={cn(
                        'segmented-option',
                        enabled
                          ? 'border-emerald-500/20 bg-emerald-500/12 text-emerald-100'
                          : 'border-rose-500/20 bg-rose-500/12 text-rose-200',
                      )}
                    >
                      {enabled ? 'Enabled' : 'Disabled'}
                    </button>
                  </div>

                  {isGlobal ? (
                    <div className="space-y-3">
                      <div>
                        <p className="detail-label">Excluded Agents</p>
                        <p className="mt-2 text-sm text-slate-400">
                          Agent slugs that should not receive this global
                          prompt.
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {excludeAgents.length === 0 ? (
                          <span className="page-pill">No exclusions</span>
                        ) : (
                          excludeAgents.map((agent) => (
                            <span
                              key={agent}
                              className="inline-flex items-center gap-1 rounded-full border border-rose-500/20 bg-rose-500/10 px-2.5 py-1 text-xs font-mono text-rose-200"
                            >
                              {agent}
                              <button
                                type="button"
                                onClick={() =>
                                  setExcludeAgents(
                                    excludeAgents.filter((a) => a !== agent),
                                  )
                                }
                                className="ml-0.5 rounded-full p-0.5 text-rose-200 transition hover:bg-rose-500/15"
                                aria-label={`Remove excluded agent ${agent}`}
                              >
                                x
                              </button>
                            </span>
                          ))
                        )}
                      </div>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={excludeInput}
                          onChange={(e) => setExcludeInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && excludeInput.trim()) {
                              e.preventDefault()
                              const val = excludeInput.trim()
                              if (!excludeAgents.includes(val)) {
                                setExcludeAgents([...excludeAgents, val])
                              }
                              setExcludeInput('')
                            }
                          }}
                          placeholder="Agent slug..."
                          className="control-input flex-1 font-mono"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            const val = excludeInput.trim()
                            if (val && !excludeAgents.includes(val)) {
                              setExcludeAgents([...excludeAgents, val])
                            }
                            setExcludeInput('')
                          }}
                          disabled={!excludeInput.trim()}
                          className="button-secondary disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          Add
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-slate-800/80 bg-slate-950/60 px-4 py-3 text-sm text-slate-400">
                      Scoped prompts follow their assignment target only, so
                      exclusions are not needed.
                    </div>
                  )}
                </div>
              </section>

              <PromptRevisionHistory
                prompt={prompt}
                revisions={revisions}
                isLoading={revisionsLoading}
                restoringRevisionId={
                  restoreMutation.isPending
                    ? (restoreMutation.variables ?? null)
                    : null
                }
                onRestore={(revisionId) => restoreMutation.mutate(revisionId)}
              />
            </aside>
          </div>
        </div>
      </div>
    </div>
  )
}
