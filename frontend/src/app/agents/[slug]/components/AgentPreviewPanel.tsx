'use client'

import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Loader2,
  RefreshCw,
} from 'lucide-react'
import { useId, useMemo, useState } from 'react'

import { cn } from '@/lib/utils'
import type {
  AgentPreview,
  AgentPreviewMemoryPlanEntry,
  PreviewProjectOption,
  PreviewScenario,
  PreviewTaskType,
} from '../types'

interface AgentPreviewPanelProps {
  preview?: AgentPreview
  previewFetching?: boolean
  previewError?: string | null
  previewMode: PreviewTaskType
  onPreviewModeChange: (mode: PreviewTaskType) => void
  scenario: PreviewScenario
  onScenarioChange: (updates: Partial<PreviewScenario>) => void
  showPreview: boolean
  onTogglePreview: () => void
  onRefresh: () => void
  projectOptions: PreviewProjectOption[]
}

const PREVIEW_MODES: Array<{ value: PreviewTaskType; label: string }> = [
  { value: 'chat', label: 'Chat' },
  { value: 'heartbeat', label: 'Heartbeat' },
  { value: 'wake', label: 'Wake' },
  { value: 'review', label: 'Review' },
]

function StatCard({
  label,
  value,
  tone = 'default',
}: {
  label: string
  value: string
  tone?: 'default' | 'warning' | 'success'
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
        {label}
      </div>
      <div
        className={cn(
          'mt-1 text-sm',
          tone === 'warning'
            ? 'text-amber-300'
            : tone === 'success'
              ? 'text-emerald-300'
              : 'text-slate-200',
        )}
      >
        {value}
      </div>
    </div>
  )
}

function formatNumber(value: number | null | undefined): string {
  return typeof value === 'number' ? value.toLocaleString() : '—'
}

function getPhaseLabel(mode: PreviewTaskType): string {
  if (mode === 'review') return 'Workstream / Phase'
  if (mode === 'wake') return 'Wake Phase Hint'
  if (mode === 'heartbeat') return 'Heartbeat Phase Hint'
  return 'Phase Hint'
}

function getPromptInputConfig(mode: PreviewTaskType) {
  if (mode === 'wake') {
    return {
      label: 'Wake Task',
      placeholder: 'Describe the task or reminder that should wake the agent.',
      helper: 'Used as the wake task text and the preview memory query.',
    }
  }
  if (mode === 'review') {
    return {
      label: 'Completion Content',
      placeholder:
        'Paste the completion or outcome text you want the review prompt to inspect.',
      helper: 'Used as the review content and the preview memory query.',
    }
  }
  return {
    label: 'User Message',
    placeholder: 'Describe the request you want to preview.',
    helper:
      'Used as the chat memory query so the memory plan matches a real request.',
  }
}

function buildWarnings(
  mode: PreviewTaskType,
  scenario: PreviewScenario,
): string[] {
  const warnings: string[] = []
  if (!scenario.projectId.trim()) {
    warnings.push(
      'Project scope is blank, so memory preview is using global-only scope.',
    )
  }
  if (mode === 'chat' && !scenario.promptInput.trim()) {
    warnings.push(
      'Chat preview has no user message yet, so the memory query will stay empty.',
    )
  }
  if (mode === 'wake' && !scenario.promptInput.trim()) {
    warnings.push(
      'Wake preview will fall back to the backend placeholder task until you add wake text.',
    )
  }
  if (mode === 'review' && !scenario.promptInput.trim()) {
    warnings.push(
      'Review preview will use placeholder completion content until you provide it.',
    )
  }
  if (mode === 'review' && !scenario.phase.trim()) {
    warnings.push(
      'Review preview will use placeholder workstream inventory until you provide a phase hint.',
    )
  }
  return warnings
}

function renderTokenSummary(entry: AgentPreviewMemoryPlanEntry): string {
  const rendered =
    typeof entry.rendered_tokens === 'number' ? entry.rendered_tokens : null
  const full = typeof entry.full_tokens === 'number' ? entry.full_tokens : null
  if (rendered == null && full == null) return '—'
  if (rendered == null) return `${full} full`
  if (full == null) return `${rendered} rendered`
  return `${rendered}/${full}`
}

export function AgentPreviewPanel({
  preview,
  previewFetching = false,
  previewError,
  previewMode,
  onPreviewModeChange,
  scenario,
  onScenarioChange,
  showPreview,
  onTogglePreview,
  onRefresh,
  projectOptions,
}: AgentPreviewPanelProps) {
  const [copied, setCopied] = useState(false)
  const projectScopeId = useId()
  const phaseHintId = useId()
  const promptInputId = useId()
  const warnings = buildWarnings(previewMode, scenario)
  const promptInputConfig = getPromptInputConfig(previewMode)
  const memoryDebug = preview?.memory_debug ?? {}
  const tierCounts = memoryDebug.tier_counts ?? {}
  const memoryPlan = useMemo(() => {
    if (!Array.isArray(memoryDebug.memory_plan)) return []
    return memoryDebug.memory_plan.slice(0, 12) as AgentPreviewMemoryPlanEntry[]
  }, [memoryDebug.memory_plan])

  const copyPreview = async () => {
    const text = preview?.full_context || preview?.combined_prompt
    if (!text) return
    await navigator.clipboard.writeText(text)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-100">
            Runtime Preview
          </h3>
          <p className="mt-1 text-xs text-slate-400">
            Build a real scenario first, then inspect the assembled prompt and
            memory plan.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {PREVIEW_MODES.map((mode) => (
            <button
              key={mode.value}
              type="button"
              onClick={() => onPreviewModeChange(mode.value)}
              className={cn(
                'rounded-full border px-3 py-1.5 text-xs font-medium transition',
                previewMode === mode.value
                  ? 'border-slate-600 bg-slate-100 text-slate-900'
                  : 'border-slate-700 text-slate-300 hover:border-slate-600',
              )}
            >
              {mode.label}
            </button>
          ))}
          <button
            type="button"
            onClick={onTogglePreview}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:bg-slate-800 cursor-pointer"
          >
            {showPreview ? 'Hide Preview' : 'Show Preview'}
          </button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <label htmlFor={projectScopeId} className="space-y-1.5">
          <span className="text-xs font-medium text-slate-400">
            Project Scope
          </span>
          <select
            id={projectScopeId}
            aria-label="Project Scope"
            value={scenario.projectId}
            onChange={(event) =>
              onScenarioChange({ projectId: event.target.value })
            }
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none transition"
          >
            <option value="">Global only</option>
            {projectOptions.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>

        <label htmlFor={phaseHintId} className="space-y-1.5">
          <span className="text-xs font-medium text-slate-400">
            {getPhaseLabel(previewMode)}
          </span>
          <input
            id={phaseHintId}
            aria-label={getPhaseLabel(previewMode)}
            value={scenario.phase}
            onChange={(event) =>
              onScenarioChange({ phase: event.target.value })
            }
            placeholder="Optional"
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none transition"
          />
        </label>
      </div>

      {previewMode !== 'heartbeat' ? (
        <label htmlFor={promptInputId} className="space-y-1.5">
          <span className="text-xs font-medium text-slate-400">
            {promptInputConfig.label}
          </span>
          <textarea
            id={promptInputId}
            aria-label={promptInputConfig.label}
            value={scenario.promptInput}
            onChange={(event) =>
              onScenarioChange({ promptInput: event.target.value })
            }
            rows={4}
            placeholder={promptInputConfig.placeholder}
            className="min-h-[96px] w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none transition"
          />
          <p className="text-[11px] text-slate-400">
            {promptInputConfig.helper}
          </p>
        </label>
      ) : (
        <div className="rounded-lg border border-dashed border-slate-700 px-3 py-2 text-[11px] text-slate-400">
          Heartbeat preview builds the task prompt from live heartbeat inputs;
          only project and phase hints matter here.
        </div>
      )}

      {warnings.length > 0 ? (
        <div className="space-y-2 rounded-lg border border-amber-900/40 bg-amber-950/20 px-3 py-3">
          {warnings.map((warning) => (
            <div
              key={warning}
              className="flex items-start gap-2 text-xs text-amber-300"
            >
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{warning}</span>
            </div>
          ))}
        </div>
      ) : null}

      {showPreview ? (
        <div className="rounded-xl bg-slate-950 p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="text-[11px] text-slate-500">
              {previewFetching
                ? 'Refreshing preview...'
                : 'Preview updates automatically as the scenario changes.'}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onRefresh()}
                disabled={previewFetching}
                className="rounded p-1.5 transition hover:bg-slate-800"
                title="Refresh preview"
              >
                <RefreshCw
                  className={cn(
                    'h-3.5 w-3.5 text-slate-400',
                    previewFetching && 'animate-spin',
                  )}
                />
              </button>
              <button
                type="button"
                onClick={copyPreview}
                disabled={!preview}
                className="rounded p-1.5 transition hover:bg-slate-800 disabled:opacity-50"
                title="Copy full context"
              >
                {copied ? (
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                ) : (
                  <Copy className="h-3.5 w-3.5 text-slate-400" />
                )}
              </button>
            </div>
          </div>

          {previewFetching && !preview ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-slate-500" />
            </div>
          ) : previewError && !preview ? (
            <div className="rounded-lg border border-rose-900/40 bg-rose-950/20 px-3 py-4 text-sm text-rose-200">
              {previewError}
            </div>
          ) : preview ? (
            <div className="space-y-4">
              <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
                <StatCard
                  label="Sections"
                  value={formatNumber(preview.sections.length)}
                />
                <StatCard
                  label="Mandates"
                  value={formatNumber(preview.mandate_count)}
                />
                <StatCard
                  label="Guardrails"
                  value={formatNumber(preview.guardrail_count)}
                />
                <StatCard
                  label="Loaded Memory"
                  value={formatNumber(preview.loaded_memory_uuids.length)}
                />
                <StatCard
                  label="Tokens"
                  value={formatNumber(memoryDebug.total_tokens)}
                />
                <StatCard
                  label="Chars Saved"
                  value={formatNumber(memoryDebug.render_chars_saved)}
                  tone={
                    typeof memoryDebug.render_chars_saved === 'number' &&
                    memoryDebug.render_chars_saved > 0
                      ? 'success'
                      : 'default'
                  }
                />
              </div>

              <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
                <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
                  <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                    Memory Query
                  </div>
                  <pre className="whitespace-pre-wrap text-xs text-slate-300">
                    {preview.memory_query || '(empty)'}
                  </pre>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
                  <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                    Render Tiers
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(tierCounts).length > 0 ? (
                      Object.entries(tierCounts).map(([tier, count]) => (
                        <span
                          key={tier}
                          className="rounded-full border border-slate-700 px-2 py-1 text-[11px] font-medium text-slate-200"
                        >
                          {tier} {count}
                        </span>
                      ))
                    ) : (
                      <span className="text-xs text-slate-500">
                        No tier data
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
                <div className="mb-2 flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
                  <span className="font-semibold uppercase tracking-[0.18em] text-slate-400">
                    Memory Plan
                  </span>
                  <span>{preview.loaded_memory_uuids.length} loaded</span>
                  <span>{preview.reference_uuids.length} references</span>
                </div>
                {memoryPlan.length > 0 ? (
                  <div className="space-y-2">
                    {memoryPlan.map((entry) => (
                      <div
                        key={`${entry.block}:${entry.uuid}`}
                        className="grid gap-2 rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 md:grid-cols-[1fr_auto_auto_auto]"
                      >
                        <div className="min-w-0">
                          <div className="truncate text-xs font-medium text-slate-200">
                            {entry.summary || entry.uuid.slice(0, 8)}
                          </div>
                          <div className="text-[11px] text-slate-500">
                            {entry.uuid.slice(0, 8)} · {entry.block}
                          </div>
                        </div>
                        <div className="text-[11px] font-medium text-slate-300">
                          {entry.tier}
                        </div>
                        <div className="text-[11px] text-slate-400">
                          {entry.reason}
                        </div>
                        <div className="text-[11px] font-mono text-slate-500">
                          {renderTokenSummary(entry)}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-slate-500">
                    No memory-plan details returned.
                  </p>
                )}
              </div>

              {preview.sections.map((section) => (
                <div
                  key={`${section.source_kind}:${section.source_id}:${section.content_hash}`}
                  className="rounded-lg border border-slate-800 bg-slate-900 p-3"
                >
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                    <span className="font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {section.label}
                    </span>
                    <span>{section.placement}</span>
                    <span>{section.source_kind}</span>
                    <span>{section.source_id}</span>
                    <span>{section.estimated_tokens} tok</span>
                  </div>
                  <pre className="whitespace-pre-wrap text-xs text-slate-300">
                    {section.content}
                  </pre>
                </div>
              ))}

              <details className="rounded-lg border border-slate-800 bg-slate-900 p-3">
                <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                  Full Context
                </summary>
                <pre className="mt-3 whitespace-pre-wrap text-xs text-slate-300">
                  {preview.full_context || preview.combined_prompt}
                </pre>
              </details>
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">
              Preview unavailable.
            </p>
          )}
        </div>
      ) : null}
    </div>
  )
}
