import type { PersonaIssueMarker } from '@/lib/api/persona-stream'
import { normalizeText, prettifyDisplayText } from './workspace-format'
import type { PreviewBadge } from './workspace-types'
import { AUTO_FOLLOW_BOTTOM_THRESHOLD } from './workspace-types'

// --- Classification helpers ---

export function eventLabel(eventType: string): string {
  return eventType.replaceAll('_', ' ')
}

export function isNearBottom(container: HTMLDivElement): boolean {
  const distanceFromBottom =
    container.scrollHeight - container.clientHeight - container.scrollTop
  return distanceFromBottom <= AUTO_FOLLOW_BOTTOM_THRESHOLD
}

export function eventToneClasses(eventType: string): string {
  if (eventType === 'error')
    return 'border-rose-900 bg-rose-950/30 text-rose-300'
  if (eventType === 'tool_result')
    return 'border-emerald-900 bg-emerald-950/30 text-emerald-300'
  if (eventType === 'tool_use')
    return 'border-sky-900 bg-sky-950/30 text-sky-300'
  if (eventType === 'thinking')
    return 'border-fuchsia-900 bg-fuchsia-950/30 text-fuchsia-300'
  return 'border-slate-800 bg-slate-950/50 text-slate-300'
}

export function eventSummaryLabel(eventType: string): string {
  if (eventType === 'assistant_message') return 'Assistant'
  if (eventType === 'user_message') return 'User'
  if (eventType === 'system_message') return 'System'
  if (eventType === 'tool_use') return 'Tool call'
  if (eventType === 'tool_result') return 'Tool result'
  if (eventType === 'error') return 'Error'
  if (eventType === 'thinking') return 'Reasoning'
  return eventLabel(eventType)
}

export function eventAccentClasses(eventType: string): string {
  if (eventType === 'error') return 'bg-rose-950/40 text-rose-300'
  if (eventType === 'tool_result') return 'bg-emerald-950/40 text-emerald-300'
  if (eventType === 'tool_use') return 'bg-sky-950/40 text-sky-300'
  if (eventType === 'assistant_message')
    return 'bg-fuchsia-950/40 text-fuchsia-300'
  return 'bg-slate-800 text-slate-300'
}

export function badgeToneClasses(
  tone: PreviewBadge['tone'] = 'neutral',
): string {
  if (tone === 'danger') return 'bg-rose-950/40 text-rose-300'
  if (tone === 'warning') return 'bg-amber-950/40 text-amber-300'
  if (tone === 'success') return 'bg-emerald-950/40 text-emerald-300'
  if (tone === 'info') return 'bg-sky-950/40 text-sky-300'
  return 'bg-slate-800 text-slate-300'
}

export function entryStatusClasses(status: string): string {
  const normalized = status.toLowerCase()
  if (normalized === 'failed' || normalized === 'error')
    return 'bg-rose-500/10 text-rose-400'
  if (normalized === 'completed') return 'bg-emerald-500/10 text-emerald-400'
  if (normalized === 'active') return 'bg-sky-500/10 text-sky-400'
  if (normalized === 'paused') return 'bg-amber-500/10 text-amber-400'
  return 'bg-slate-800/60 text-slate-400'
}

export function outcomeToneClasses(hasErrors: boolean): string {
  return hasErrors
    ? 'bg-rose-950/40 text-rose-300'
    : 'bg-emerald-950/40 text-emerald-300'
}

export function rootCauseClasses(rootCause: string): string {
  switch (rootCause) {
    case 'workflow':
      return 'bg-fuchsia-950/40 text-fuchsia-300'
    case 'tool':
      return 'bg-sky-950/40 text-sky-300'
    case 'context':
      return 'bg-amber-950/40 text-amber-300'
    case 'infra':
      return 'bg-rose-950/40 text-rose-300'
    case 'prompt':
      return 'bg-violet-950/40 text-violet-300'
    default:
      return 'bg-slate-800 text-slate-300'
  }
}

export function compactPath(path: string): string {
  const segments = path.split('/').filter(Boolean)
  if (segments.length <= 3) return path
  return `.../${segments.slice(-3).join('/')}`
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function humanizeFieldLabel(value: string): string {
  return value
    .replaceAll('.', ' ')
    .replaceAll('_', ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

export function isPromptLikeText(value: string | null): boolean {
  if (!value) return false
  const normalized = value.toLowerCase()
  return (
    normalized.includes('# persona safety boundaries') ||
    normalized.includes('<persona_context>') ||
    normalized.includes('<heartbeat_instructions>') ||
    (value.length > 900 && value.split('\n').length > 20)
  )
}

export function isGenericStatusText(value: string | null): boolean {
  if (!value) return false
  const normalized = normalizeText(value)
  return (
    normalized === 'execution completed' ||
    normalized === 'session started' ||
    normalized === 'new message' ||
    normalized === 'tool' ||
    normalized.startsWith('waiting for model after')
  )
}

export function shouldRenderPulseSummary(
  summary: string | null,
  issueMarkers: PersonaIssueMarker[],
): boolean {
  if (!summary) return false
  if (issueMarkers.length > 0) return false
  const normalizedSummary = normalizeText(prettifyDisplayText(summary))
  if (!normalizedSummary || isGenericStatusText(normalizedSummary)) return false
  return !issueMarkers.some((marker) => {
    const markerText = normalizeText(
      prettifyDisplayText(
        `${marker.title}\n${marker.detail ?? marker.summary}`,
      ),
    )
    return (
      markerText === normalizedSummary ||
      markerText.includes(normalizedSummary) ||
      normalizedSummary.includes(markerText)
    )
  })
}

// --- Heartbeat classification ---

export function heartbeatIsImportant(entry: {
  display_summary?: string | null
  summary_oneliner?: string | null
  live_summary?: string | null
}): boolean {
  const summary =
    `${entry.display_summary ?? ''} ${entry.summary_oneliner ?? ''} ${entry.live_summary ?? ''}`.toLowerCase()
  const importantKeywords = [
    'dispatch',
    'publish',
    'verified',
    'verify',
    'fixed',
    'created ',
    'reconciled',
    'merged',
    'review',
    'audit',
    'error',
    'failed',
    'blocked',
    'warning',
    'assess',
    'investig',
    'task-',
  ]
  return importantKeywords.some((keyword) => summary.includes(keyword))
}
