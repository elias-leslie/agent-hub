import type { LiveActivity, Session, SessionListItem } from '@/lib/api/sessions'
import { formatRelativeTime, formatTokens } from '@/lib/formatters'
import { estimateTokenCost } from '@/lib/model-pricing'
import type { ModelCost } from '@/lib/models'

// Re-exported from canonical location
export { formatRelativeTime, formatTokens }

export function formatTokenPair(input: number, output: number): string {
  return `in ${formatTokens(input)} · out ${formatTokens(output)}`
}

export function estimateCost(
  model: string,
  inputTokens: number,
  outputTokens: number,
  modelCosts: Map<string, ModelCost>,
): number {
  return estimateTokenCost(model, inputTokens, outputTokens, modelCosts)
}

export function formatCost(cost: number): string {
  if (cost === 0) return '$0'
  if (cost < 0.0001) return '<$0.0001'
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  if (cost < 1) return `$${cost.toFixed(3)}`
  return `$${cost.toFixed(2)}`
}

export type SessionDisplayStatusKey =
  | 'working'
  | 'stalled'
  | 'reapable'
  | 'failed'
  | 'ended'

export interface SessionDisplayStatus {
  key: SessionDisplayStatusKey
  label: string
  rank: number
  dotClassName: string
  badgeClassName: string
  tooltip: string
}

function normalizedLiveState(liveActivity?: LiveActivity | null): string {
  return String(
    liveActivity?.lifecycle_state ||
      liveActivity?.status ||
      liveActivity?.phase ||
      '',
  ).toLowerCase()
}

export function getSessionDisplayStatus(
  session: Pick<SessionListItem | Session, 'status' | 'live_activity'>,
): SessionDisplayStatus {
  const liveActivity = session.live_activity
  const liveState = normalizedLiveState(liveActivity)
  const storedStatus = String(session.status || '').toLowerCase()

  if (storedStatus === 'failed' || storedStatus === 'error') {
    return {
      key: 'failed',
      label: 'Failed',
      rank: 2,
      dotClassName: 'bg-rose-400',
      badgeClassName: 'border-rose-400/45 bg-rose-400/10',
      tooltip: 'Failed',
    }
  }

  if (storedStatus !== 'active') {
    return {
      key: 'ended',
      label: 'Ended',
      rank: 3,
      dotClassName: 'bg-slate-500',
      badgeClassName: 'border-slate-500/45 bg-slate-500/10',
      tooltip: 'Ended',
    }
  }

  if (liveActivity?.reapable || liveState === 'reapable') {
    return {
      key: 'reapable',
      label: 'Reapable',
      rank: 1,
      dotClassName: 'bg-amber-300',
      badgeClassName: 'border-amber-300/40 bg-amber-400/10',
      tooltip: 'Reapable',
    }
  }

  if (
    liveActivity?.stalled ||
    liveState === 'stalled' ||
    liveState === 'stale'
  ) {
    return {
      key: 'stalled',
      label: 'Stalled',
      rank: 1,
      dotClassName: 'bg-amber-400',
      badgeClassName: 'border-amber-400/45 bg-amber-400/10',
      tooltip: 'Stalled',
    }
  }

  if (
    liveState === 'working' ||
    liveState === 'active' ||
    liveState === 'running'
  ) {
    return {
      key: 'working',
      label: 'Working',
      rank: 0,
      dotClassName: 'bg-emerald-400',
      badgeClassName: 'border-emerald-400/45 bg-emerald-400/10',
      tooltip: 'Working',
    }
  }

  return {
    key: 'working',
    label: 'Working',
    rank: 0,
    dotClassName: 'bg-emerald-400',
    badgeClassName: 'border-emerald-400/45 bg-emerald-400/10',
    tooltip: 'Working',
  }
}

export function getSessionDescription(session: SessionListItem): string {
  const liveSummary = session.live_activity?.summary?.trim()
  const summary = session.summary_oneliner?.trim()
  const attribution = session.attribution_label?.trim()
  const attributionDetail = session.attribution_detail?.trim()
  const currentTopic = session.live_activity?.current_topic?.trim()
  const currentTool = session.live_activity?.current_tool_name?.trim()
  const requestSource = session.request_source?.trim()
  const externalId = session.external_id?.trim()

  return (
    liveSummary ||
    summary ||
    attribution ||
    attributionDetail ||
    currentTopic ||
    currentTool ||
    requestSource ||
    externalId ||
    `session ${session.id.slice(0, 8)}`
  )
}

export function getSessionDescriptionTitle(session: SessionListItem): string {
  const parts = [
    session.summary_oneliner,
    session.live_activity?.summary,
    session.attribution_label,
    session.attribution_detail,
    session.request_source,
    session.external_id,
    session.id,
  ]
    .map((value) => value?.trim())
    .filter(Boolean)

  return parts.join(' · ')
}

export function formatDurationMs(diffMs: number): string {
  if (diffMs < 1000) return `${Math.max(diffMs, 0)}ms`
  if (diffMs < 60000) return `${(diffMs / 1000).toFixed(1)}s`
  const totalMinutes = Math.floor(diffMs / 60000)
  if (totalMinutes < 60) {
    return `${totalMinutes}m ${Math.floor((diffMs % 60000) / 1000)}s`
  }
  const hours = Math.floor(totalMinutes / 60)
  if (hours < 48) return `${hours}h ${totalMinutes % 60}m`
  return `${Math.floor(hours / 24)}d ${hours % 24}h`
}

export function formatDuration(startDate: string, endDate: string): string {
  return formatDurationMs(
    new Date(endDate).getTime() - new Date(startDate).getTime(),
  )
}

type TitleSource = Pick<
  SessionListItem,
  'id' | 'title' | 'summary_oneliner' | 'current_branch'
>

/** Most distinguishing human label: first prompt, then summary, branch, id. */
export function getSessionTitle(session: TitleSource): string {
  return (
    session.title?.trim() ||
    session.summary_oneliner?.trim() ||
    session.current_branch?.trim() ||
    `session ${session.id.slice(0, 8)}`
  )
}

export function getSessionKindLabel(sessionType: string): string {
  switch (sessionType) {
    case 'agent':
    case 'claude_code':
      return 'coding'
    case 'image_generation':
      return 'image'
    default:
      return sessionType || 'unknown'
  }
}

/** The harness or provider a person recognises: "codex", "claude code", "gemini chat". */
export function getSessionSourceLabel(
  session: Pick<SessionListItem, 'session_type' | 'provider'>,
): string {
  if (session.session_type === 'claude_code') return 'claude code'
  if (session.session_type === 'agent') return session.provider || 'agent'
  return `${session.provider} ${getSessionKindLabel(session.session_type)}`
}

/** Matches the server's coalesce(last_activity_at, created_at); updated_at is bulk-touched. */
export function getSessionLastActive(
  session: Pick<SessionListItem, 'last_active_at' | 'created_at'>,
): string {
  return session.last_active_at || session.created_at
}

type UsageSource = Pick<
  SessionListItem,
  | 'usage_known'
  | 'usage_input_tokens'
  | 'usage_output_tokens'
  | 'usage_cached_input_tokens'
  | 'total_input_tokens'
  | 'total_output_tokens'
>

export interface UsageSummary {
  known: boolean
  input: number
  output: number
  cached: number
  label: string
  title: string
}

/** Native usage events first, stored message counters second, otherwise honestly unknown. */
export function getUsageSummary(session: UsageSource): UsageSummary {
  if (session.usage_known) {
    const input = session.usage_input_tokens ?? 0
    const output = session.usage_output_tokens ?? 0
    const cached = session.usage_cached_input_tokens ?? 0
    return {
      known: true,
      input,
      output,
      cached,
      label: `${formatTokens(input)} / ${formatTokens(output)}`,
      title: `Input ${formatTokens(input)} (cached ${formatTokens(cached)}) · output ${formatTokens(output)}`,
    }
  }
  const input = session.total_input_tokens ?? 0
  const output = session.total_output_tokens ?? 0
  if (input > 0 || output > 0) {
    return {
      known: true,
      input,
      output,
      cached: 0,
      label: `${formatTokens(input)} / ${formatTokens(output)}`,
      title: `Input ${formatTokens(input)} · output ${formatTokens(output)} (message counters)`,
    }
  }
  return {
    known: false,
    input: 0,
    output: 0,
    cached: 0,
    label: 'not captured',
    title: 'This harness did not report token usage for the session',
  }
}

export function sinceToIso(
  preset: 'today' | '7d' | '30d' | 'all',
  now: Date = new Date(),
): string | undefined {
  if (preset === 'all') return undefined
  if (preset === 'today') {
    const start = new Date(now)
    start.setHours(0, 0, 0, 0)
    return start.toISOString()
  }
  const days = preset === '7d' ? 7 : 30
  return new Date(now.getTime() - days * 86_400_000).toISOString()
}

type ExecutionIdentitySource = Pick<
  SessionListItem | Session,
  | 'provider'
  | 'model'
  | 'requested_provider'
  | 'requested_model'
  | 'effective_provider'
  | 'effective_model'
  | 'requested_model_display_name'
  | 'effective_model_display_name'
  | 'fallback_used'
  | 'fallback_reason'
>

function isUnknownModel(model: string | null | undefined): boolean {
  const value = model?.trim().toLowerCase() ?? ''
  return value === 'unknown' || value.endsWith('/unknown')
}

function coalesceLabel(
  ...values: Array<string | null | undefined>
): string | null {
  for (const value of values) {
    if (value && value.trim().length > 0) {
      return value
    }
  }
  return null
}

export function getExecutionIdentity(source: ExecutionIdentitySource) {
  const requestedModel = coalesceLabel(
    source.requested_model_display_name,
    source.requested_model,
  )
  // Harnesses such as Codex report "unknown" until a model is observed; that is
  // missing evidence, not a fallback to another model.
  const observedModel = coalesceLabel(
    source.effective_model_display_name,
    source.effective_model,
  )
  const effectiveModel =
    (observedModel && !isUnknownModel(observedModel)
      ? observedModel
      : coalesceLabel(
          requestedModel,
          isUnknownModel(source.model) ? null : source.model,
        )) ?? source.model
  const requestedProvider = coalesceLabel(
    source.requested_provider,
    source.provider,
  )
  const effectiveProvider =
    coalesceLabel(source.effective_provider, source.provider) ?? source.provider
  const showRequested = Boolean(
    requestedModel && requestedModel !== effectiveModel,
  )
  const fallbackReason = coalesceLabel(source.fallback_reason)
  const fallbackUsed = Boolean(
    source.fallback_used || showRequested || fallbackReason,
  )

  return {
    requestedModel,
    effectiveModel,
    requestedProvider,
    effectiveProvider,
    showRequested,
    fallbackUsed,
    fallbackReason,
  }
}
