'use client'

import { AlertTriangle } from 'lucide-react'
import type { ContextUsage } from '@/lib/api/sessions'
import type { AgentPreview } from '@/types/agent-preview'
import { EvidencePanel, SectionEyebrow } from './persona-operator-chrome'

interface PersonaPromptBudgetPanelProps {
  preview: AgentPreview | null
  loading: boolean
  error: string | null
  runtimeContext?: ContextUsage | null
}

export function PersonaPromptBudgetPanel({
  preview,
  loading,
  error,
  runtimeContext = null,
}: PersonaPromptBudgetPanelProps) {
  const totalTokens = preview?.memory_debug?.total_tokens
  const sections = [...(preview?.sections ?? [])]
    .sort((left, right) => right.estimated_tokens - left.estimated_tokens)
    .slice(0, 3)

  return (
    <EvidencePanel data-testid="persona-prompt-budget-panel" className="p-4">
      <SectionEyebrow
        label="Context"
        source={runtimeContext ? 'runtime' : 'preview'}
      />

      <div className="mt-3 text-sm text-slate-300">
        {runtimeContext
          ? `${Math.round(runtimeContext.percent_used)}% live used · ${runtimeContext.remaining_tokens.toLocaleString()} left`
          : loading
            ? 'Loading preview budget…'
            : typeof totalTokens === 'number'
              ? `${totalTokens.toLocaleString()} preview tokens`
              : 'Preview unavailable'}
        {typeof totalTokens === 'number'
          ? ` · preview ${totalTokens.toLocaleString()}`
          : ''}
      </div>

      {typeof totalTokens === 'number' && totalTokens >= 14000 ? (
        <div className="mt-3 inline-flex items-center gap-2 text-sm text-amber-200">
          <AlertTriangle className="h-4 w-4" />
          Preview is heavy.
        </div>
      ) : null}

      {sections.length > 0 ? (
        <div className="mt-3 space-y-1 text-xs text-slate-500">
          {sections.map((section) => (
            <div
              key={`${section.source_kind}:${section.source_id}:${section.content_hash}`}
              className="flex items-center justify-between gap-3"
            >
              <span className="truncate">{section.label}</span>
              <span className="font-mono text-slate-400">
                {section.estimated_tokens.toLocaleString()} tok
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {error ? <div className="mt-3 text-sm text-rose-300">{error}</div> : null}
    </EvidencePanel>
  )
}
