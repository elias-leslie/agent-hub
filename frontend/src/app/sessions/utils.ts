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

export function formatDuration(startDate: string, endDate: string): string {
  const start = new Date(startDate).getTime()
  const end = new Date(endDate).getTime()
  const diffMs = end - start
  if (diffMs < 1000) return `${diffMs}ms`
  if (diffMs < 60000) return `${(diffMs / 1000).toFixed(1)}s`
  return `${Math.floor(diffMs / 60000)}m ${Math.floor((diffMs % 60000) / 1000)}s`
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
  const effectiveModel =
    coalesceLabel(
      source.effective_model_display_name,
      source.effective_model,
      source.model,
    ) ?? source.model
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
