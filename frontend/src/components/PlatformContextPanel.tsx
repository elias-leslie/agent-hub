'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Eye,
  EyeOff,
  Globe2,
  Loader2,
  Save,
  Sparkles,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import {
  createPrompt,
  fetchOptionalPrompt,
  PLATFORM_CONTEXT_PROMPT_SLUG,
  updatePrompt,
} from '@/lib/api/prompts'
import { cn } from '@/lib/utils'

async function fetchPlatformContext() {
  return fetchOptionalPrompt(PLATFORM_CONTEXT_PROMPT_SLUG)
}

function truncatePreview(content: string, maxLength = 120): string {
  if (!content) return 'No platform context configured'
  const firstLine = content.split('\n')[0]
  return firstLine.length <= maxLength
    ? firstLine
    : `${firstLine.slice(0, maxLength).trim()}…`
}

function usePlatformContext() {
  const queryClient = useQueryClient()
  const [editedContent, setEditedContent] = useState<string | null>(null)
  const [showSuccess, setShowSuccess] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['prompt', PLATFORM_CONTEXT_PROMPT_SLUG],
    queryFn: fetchPlatformContext,
  })

  const mutation = useMutation({
    mutationFn: async (payload: { content?: string; enabled?: boolean }) => {
      if (!data) {
        return createPrompt({
          slug: PLATFORM_CONTEXT_PROMPT_SLUG,
          name: 'Platform Context',
          content: payload.content ?? '',
          description:
            'Platform-wide context injected into all agents as <platform_context>.',
          is_global: true,
          enabled: payload.enabled ?? true,
        })
      }
      return updatePrompt(PLATFORM_CONTEXT_PROMPT_SLUG, payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['prompt', PLATFORM_CONTEXT_PROMPT_SLUG],
      })
      queryClient.invalidateQueries({ queryKey: ['prompts'] })
      setEditedContent(null)
      setShowSuccess(true)
      setTimeout(() => setShowSuccess(false), 2000)
    },
  })

  useEffect(() => {
    if (editedContent === null) setEditedContent(data?.content ?? '')
  }, [data, editedContent])

  const handleSave = useCallback(() => {
    if (editedContent !== null) mutation.mutate({ content: editedContent })
  }, [editedContent, mutation])

  const handleToggleEnabled = useCallback(() => {
    mutation.mutate({ enabled: !(data?.enabled ?? true) })
  }, [data, mutation])

  return {
    data,
    isLoading,
    error,
    editedContent,
    setEditedContent,
    hasChanges:
      editedContent !== null && editedContent !== (data?.content ?? ''),
    showSuccess,
    mutation,
    handleSave,
    handleToggleEnabled,
  }
}

function CollapsedHeader({
  isExpanded,
  isEnabled,
  content,
  activeAgentCount,
  onToggle,
}: {
  isExpanded: boolean
  isEnabled: boolean
  content: string
  activeAgentCount: number
  onToggle: () => void
}) {
  return (
    <button
      onClick={onToggle}
      className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-slate-800/30"
    >
      <div className="flex items-center gap-3 min-w-0">
        <div
          className={cn(
            'flex h-9 w-9 items-center justify-center rounded-xl border border-slate-800/70 transition-colors',
            isEnabled
              ? 'bg-amber-900/30 text-amber-300'
              : 'bg-slate-900 text-slate-400',
          )}
        >
          <Globe2
            className={cn(
              'h-4 w-4',
              isEnabled ? 'text-amber-400' : 'text-slate-400',
            )}
          />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'text-xs font-semibold uppercase tracking-[0.18em]',
                isEnabled ? 'text-amber-300' : 'text-slate-500',
              )}
            >
              Platform Context
            </span>
            {!isEnabled && (
              <span className="rounded-full bg-slate-800 px-2 py-1 text-[9px] font-bold uppercase tracking-[0.18em] text-slate-400">
                Disabled
              </span>
            )}
          </div>
          <p className="mt-1 truncate text-xs text-slate-400">
            {truncatePreview(content)}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3 flex-shrink-0 ml-4">
        <div className="hidden items-center gap-1.5 rounded-full border border-slate-700/60 bg-slate-900/70 px-2.5 py-1 sm:flex">
          <Sparkles className="h-3 w-3 text-slate-400" />
          <span className="text-[10px] font-medium text-slate-400">
            {activeAgentCount} agent{activeAgentCount !== 1 ? 's' : ''}
          </span>
        </div>
        <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-slate-800/70 bg-slate-900/70">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-slate-400" />
          ) : (
            <ChevronRight className="h-4 w-4 text-slate-400" />
          )}
        </div>
      </div>
    </button>
  )
}

function Toolbar({
  isEnabled,
  hasChanges,
  showSuccess,
  isPending,
  onToggle,
  onSave,
}: {
  isEnabled: boolean
  hasChanges: boolean
  showSuccess: boolean
  isPending: boolean
  onToggle: () => void
  onSave: () => void
}) {
  return (
    <div className="flex items-center justify-between py-4">
      <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
        DB-backed global prompt injected into all agents
      </p>
      <div className="flex items-center gap-2">
        <button
          onClick={(e) => {
            e.stopPropagation()
            onToggle()
          }}
          disabled={isPending}
          className={cn(
            'flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium transition-colors',
            isEnabled
              ? 'bg-amber-900/30 text-amber-300 hover:bg-amber-900/50'
              : 'bg-slate-800 text-slate-500 hover:bg-slate-700',
          )}
        >
          {isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : isEnabled ? (
            <Eye className="h-3.5 w-3.5" />
          ) : (
            <EyeOff className="h-3.5 w-3.5" />
          )}
          {isEnabled ? 'Enabled' : 'Disabled'}
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation()
            onSave()
          }}
          disabled={!hasChanges || isPending}
          className={cn(
            'flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold transition-all',
            hasChanges
              ? 'bg-amber-500 text-slate-950 hover:bg-amber-400 shadow-[0_16px_28px_-22px_rgba(245,158,11,0.9)]'
              : 'bg-slate-800 text-slate-400 cursor-not-allowed',
          )}
        >
          {isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : showSuccess ? (
            <CheckCircle2 className="h-3.5 w-3.5" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          {showSuccess ? 'Saved' : 'Save'}
        </button>
      </div>
    </div>
  )
}

function Editor({
  content,
  isEnabled,
  onChange,
}: {
  content: string
  isEnabled: boolean
  onChange: (value: string) => void
}) {
  return (
    <div className="relative">
      <textarea
        value={content}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Enter platform-wide context shared by all agents..."
        rows={8}
        className={cn(
          'min-h-[170px] max-h-[calc(100vh-20rem)] w-full resize-y rounded-2xl border px-4 py-4 text-sm font-mono leading-relaxed focus:outline-none focus:ring-2 transition-colors',
          isEnabled
            ? 'bg-slate-950/80 border-amber-900/50 focus:ring-amber-500/30 focus:border-amber-400'
            : 'bg-slate-900/50 border-slate-800 focus:ring-slate-500/30 text-slate-500',
        )}
      />
      <div className="absolute bottom-2 right-2">
        <span className="text-[10px] font-mono text-slate-400 bg-slate-900/80 px-1.5 py-0.5 rounded">
          {content.length.toLocaleString()} chars
        </span>
      </div>
    </div>
  )
}

export function PlatformContextPanel({
  activeAgentCount,
}: {
  activeAgentCount: number
}) {
  const [isExpanded, setIsExpanded] = useState(false)
  const {
    data,
    isLoading,
    error,
    editedContent,
    setEditedContent,
    hasChanges,
    showSuccess,
    mutation,
    handleSave,
    handleToggleEnabled,
  } = usePlatformContext()

  if (isLoading)
    return (
      <div className="mb-5">
        <div className="h-12 rounded-lg bg-slate-800/50 animate-pulse" />
      </div>
    )

  if (error) {
    return (
      <div className="mb-5 flex items-center gap-2 px-4 py-3 rounded-lg bg-red-950/20 border border-red-900 text-red-400">
        <AlertCircle className="h-4 w-4 flex-shrink-0" />
        <span className="text-xs">Failed to load platform context</span>
      </div>
    )
  }

  const content = editedContent ?? data?.content ?? ''
  const isEnabled = data?.enabled ?? true

  return (
    <div className="mb-5">
      <div
        className={cn(
          'overflow-hidden rounded-2xl border transition-all duration-200',
          isEnabled
            ? 'border-amber-700/40 bg-[linear-gradient(135deg,rgba(120,53,15,0.26),rgba(15,23,42,0.8))]'
            : 'border-slate-800 bg-slate-900/60',
        )}
      >
        <CollapsedHeader
          isExpanded={isExpanded}
          isEnabled={isEnabled}
          content={content}
          activeAgentCount={activeAgentCount}
          onToggle={() => setIsExpanded(!isExpanded)}
        />
        {isExpanded && (
          <div className="border-t border-slate-700/50 px-5 pb-5">
            <Toolbar
              isEnabled={isEnabled}
              hasChanges={hasChanges}
              showSuccess={showSuccess}
              isPending={mutation.isPending}
              onToggle={handleToggleEnabled}
              onSave={handleSave}
            />
            <Editor
              content={content}
              isEnabled={isEnabled}
              onChange={setEditedContent}
            />
            <div className="mt-3 flex items-start gap-2 text-[10px] text-slate-400">
              <div className="w-1 h-1 rounded-full bg-slate-600 mt-1.5 flex-shrink-0" />
              <p>
                This is the canonical DB-backed prompt injected into every agent
                as{' '}
                <code className="px-1 py-0.5 rounded bg-slate-800 font-mono">
                  &lt;platform_context&gt;
                </code>
                . Review it in the Prompts UI or any agent&apos;s combined
                preview.
              </p>
            </div>
          </div>
        )}
      </div>
      {mutation.isError && (
        <div className="mt-2 flex items-center gap-2 rounded-2xl border border-red-900 bg-red-950/20 px-3 py-2 text-red-400">
          <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
          <span className="text-xs">Failed to save changes</span>
        </div>
      )}
    </div>
  )
}
