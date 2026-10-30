/**
 * Sessions and session events API
 */

import type { SessionEventsResponse, TimelineEvent } from '@/types/events'
import { fetchApi, getApiBaseUrl } from '../api-config'
import {
  type AccountingWindow,
  type DurationSplit,
  isAccountingWindow,
  isDurationSplit,
  isRecord,
  isSessionWorkRole,
  isWorkRoleOption,
  type SessionWorkRole,
  type WorkRoleOption,
} from './duration-split'

export type SessionTimelineEvent = TimelineEvent
export type { SessionEventsResponse }

const API_BASE = `${getApiBaseUrl()}/api`
const SESSION_EVENTS_MAX_PAGE_SIZE = 500

export interface SessionMessage {
  id: number
  role: string
  content: string
  tokens: number | null
  agent_id: string | null
  agent_name: string | null
  created_at: string
}

export interface AgentTokenBreakdown {
  agent_id: string
  agent_name: string | null
  input_tokens: number
  output_tokens: number
  total_tokens: number
  message_count: number
}

export interface ContextUsage {
  used_tokens: number
  limit_tokens: number
  percent_used: number
  remaining_tokens: number
  warning: string | null
  measured?: boolean
}

export interface LiveActivity {
  phase: string
  status: string
  summary?: string | null
  health: string
  stalled: boolean
  stall_reason?: string | null
  quiet_for_seconds?: number | null
  last_event_type?: string | null
  last_event_at?: string | null
  last_model_activity_at?: string | null
  current_tool_name?: string | null
  current_topic?: string | null
  last_tool_name?: string | null
  last_topic?: string | null
  last_tool_started_at?: string | null
  last_tool_finished_at?: string | null
  last_tool_error?: boolean | null
  last_read_path?: string | null
  last_write_path?: string | null
  last_command?: string | null
  last_validation_command?: string | null
  last_command_exit_code?: number | null
  outstanding_tool_calls: number
  tool_calls_count: number
  termination_reason?: string | null
  files_touched: string[]
  last_heartbeat_at?: string | null
  lifecycle_state?: string
  lifecycle_reason_codes?: string[]
  dead_signals?: string[]
  anti_reap_signals?: string[]
  has_owner_lane?: boolean
  has_specialist_lane?: boolean
  reapable?: boolean
  reapable_reason?: string | null
}

export interface RequestErrors {
  count: number
  last_category: string
  last_message: string
}

export interface Session {
  request_errors?: RequestErrors | null
  work_role?: SessionWorkRole | null
  id: string
  project_id: string
  provider: string
  model: string
  requested_provider?: string | null
  requested_model?: string | null
  effective_provider?: string | null
  effective_model?: string | null
  requested_model_display_name?: string | null
  effective_model_display_name?: string | null
  fallback_used?: boolean
  fallback_reason?: string | null
  status: string
  agent_slug: string | null
  session_type: string
  parent_session_id?: string | null
  external_id?: string | null
  client_id?: string | null
  request_source?: string | null
  source_client?: string | null
  source_path?: string | null
  attribution_kind?: string | null
  attribution_label?: string | null
  attribution_detail?: string | null
  current_branch?: string | null
  working_dir?: string | null
  repo_root?: string | null
  host?: string | null
  tmux_session_name?: string | null
  tmux_pane_id?: string | null
  workstream_status?: string | null
  summary_oneliner?: string | null
  child_session_count?: number | null
  active_child_session_count?: number | null
  batch_task_ids?: string[]
  declared_scope_paths?: string[]
  observed_read_paths?: string[]
  observed_write_paths?: string[]
  scope_confidence?: string | null
  created_at: string
  updated_at: string
  live_activity?: LiveActivity | null
  messages?: SessionMessage[]
  context_usage?: ContextUsage | null
  agent_token_breakdown?: AgentTokenBreakdown[]
  message_count?: number | null
  event_count?: number | null
  total_input_tokens?: number
  total_output_tokens?: number
  title?: string | null
  usage_known?: boolean
  usage_input_tokens?: number | null
  usage_output_tokens?: number | null
  usage_cached_input_tokens?: number | null
  last_active_at?: string | null
}

export interface SessionListItem {
  request_errors?: RequestErrors | null
  work_role?: SessionWorkRole | null
  activity_accounting?: DurationSplit | null
  id: string
  project_id: string
  provider: string
  model: string
  requested_provider?: string | null
  requested_model?: string | null
  effective_provider?: string | null
  effective_model?: string | null
  requested_model_display_name?: string | null
  effective_model_display_name?: string | null
  fallback_used?: boolean
  fallback_reason?: string | null
  status: string
  agent_slug: string | null
  session_type: string
  parent_session_id?: string | null
  external_id?: string | null
  client_id?: string | null
  request_source?: string | null
  source_client?: string | null
  source_path?: string | null
  attribution_kind?: string | null
  attribution_label?: string | null
  attribution_detail?: string | null
  current_branch?: string | null
  summary_oneliner?: string | null
  live_activity?: LiveActivity | null
  declared_scope_paths?: string[]
  observed_read_paths?: string[]
  observed_write_paths?: string[]
  scope_confidence?: string | null
  message_count: number
  event_count?: number | null
  total_input_tokens: number
  total_output_tokens: number
  child_session_count?: number | null
  active_child_session_count?: number | null
  title?: string | null
  usage_known?: boolean
  usage_input_tokens?: number | null
  usage_output_tokens?: number | null
  usage_cached_input_tokens?: number | null
  last_active_at?: string | null
  created_at: string
  updated_at: string
}

export interface SessionListResponse {
  accounting_window?: AccountingWindow
  work_roles?: WorkRoleOption[]
  harnesses?: WorkRoleOption[]
  sessions: SessionListItem[]
  total: number
  page: number
  page_size: number
  next_cursor?: string | null
}

/** Coarse session kinds over the stored session_type (coding = agent | claude_code). */
export type SessionKind = 'coding' | 'chat' | 'completion' | 'image'
export const SESSION_KINDS: readonly SessionKind[] = [
  'coding',
  'chat',
  'completion',
  'image',
]

export interface SessionListQuery {
  accounting_start?: string
  accounting_end?: string
  work_role?: string
  harness?: string
  q?: string
  kind?: readonly SessionKind[]
  status?: string
  since?: string
  project_id?: string
  model?: string
  roots_only?: boolean
  exclude_benchmarks?: boolean
  parent_session_id?: string
  /** time = coalesce(last_activity_at, updated_at, created_at). */
  sort_by?:
    | 'last_active'
    | 'status'
    | 'time'
    | 'admin_share'
    | 'admin_tokens'
    | 'admin_duration'
  sort_direction?: 'asc' | 'desc'
  cursor?: string
  page_size?: number
}

export interface SessionFacets {
  work_roles?: WorkRoleOption[]
  harnesses?: WorkRoleOption[]
  status: Record<string, number>
  kind: Record<SessionKind, number>
  projects: { project_id: string; count: number }[]
}

export interface SessionEventsSummary {
  total: number
  by_type: Record<string, number>
  first_user_message?: string | null
  usage_known?: boolean
  usage_input_tokens?: number | null
  usage_output_tokens?: number | null
  usage_cached_input_tokens?: number | null
}

export function sessionListSearchParams(
  query: SessionListQuery,
): URLSearchParams {
  const params = new URLSearchParams()
  for (const key of [
    'accounting_start',
    'accounting_end',
    'work_role',
    'harness',
  ] as const) {
    if (query[key]) params.set(key, query[key])
  }
  if (query.q) params.set('q', query.q)
  if (query.kind?.length) params.set('kind', query.kind.join(','))
  if (query.status) params.set('status', query.status)
  if (query.since) params.set('since', query.since)
  if (query.project_id) params.set('project_id', query.project_id)
  if (query.model) params.set('model', query.model)
  if (query.roots_only) params.set('roots_only', 'true')
  if (query.exclude_benchmarks) params.set('exclude_benchmarks', 'true')
  if (query.parent_session_id)
    params.set('parent_session_id', query.parent_session_id)
  if (query.sort_by) params.set('sort_by', query.sort_by)
  if (query.sort_direction) params.set('sort_direction', query.sort_direction)
  if (query.cursor) params.set('cursor', query.cursor)
  if (query.page_size) params.set('page_size', String(query.page_size))
  return params
}

/** Server-filtered, keyset-paged session list. */
export async function querySessions(
  query: SessionListQuery,
): Promise<SessionListResponse> {
  const response = await fetchApi(
    `${API_BASE}/sessions?${sessionListSearchParams(query)}`,
  )
  if (!response.ok) {
    throw new Error(`Sessions fetch failed: ${response.status}`)
  }
  return parseSessionListResponse(await response.json())
}

/** Validate additive accounting fields; older servers keep them unavailable. */
export function parseSessionListResponse(value: unknown): SessionListResponse {
  if (
    !isRecord(value) ||
    !Array.isArray(value.sessions) ||
    typeof value.total !== 'number' ||
    !value.sessions.every(
      (row: unknown) =>
        isRecord(row) &&
        typeof row.id === 'string' &&
        (row.activity_accounting == null ||
          isDurationSplit(row.activity_accounting)) &&
        (row.work_role == null || isSessionWorkRole(row.work_role)),
    ) ||
    (value.accounting_window !== undefined &&
      !isAccountingWindow(value.accounting_window)) ||
    ['work_roles', 'harnesses'].some(
      (key) =>
        value[key] !== undefined &&
        (!Array.isArray(value[key]) || !value[key].every(isWorkRoleOption)),
    )
  )
    throw new Error('Session accounting data is incomplete or invalid')
  return value as unknown as SessionListResponse
}

/** Facet counts for the same filters; each facet ignores its own filter. */
export async function fetchSessionFacets(
  query: Omit<
    SessionListQuery,
    'cursor' | 'page_size' | 'sort_by' | 'sort_direction'
  >,
): Promise<SessionFacets> {
  const response = await fetchApi(
    `${API_BASE}/sessions/facets?${sessionListSearchParams(query)}`,
  )
  if (!response.ok) {
    throw new Error(`Session facets fetch failed: ${response.status}`)
  }
  const value: unknown = await response.json()
  if (
    !isRecord(value) ||
    ['work_roles', 'harnesses'].some(
      (key) =>
        value[key] !== undefined &&
        (!Array.isArray(value[key]) || !value[key].every(isWorkRoleOption)),
    )
  )
    throw new Error('Session filters are incomplete or invalid')
  return value as unknown as SessionFacets
}

export async function fetchSessionEventsSummary(
  sessionId: string,
): Promise<SessionEventsSummary> {
  const response = await fetchApi(
    `${API_BASE}/sessions/${sessionId}/events/summary`,
  )
  if (!response.ok) {
    throw new Error(`Session events summary fetch failed: ${response.status}`)
  }
  return response.json()
}

export async function fetchSessions(params?: {
  project_id?: string
  status?: string
  agent_slug?: string
  session_type?: string
  parent_session_id?: string
  external_id?: string
  sort_by?: 'agent' | 'project' | 'status' | 'time'
  sort_direction?: 'asc' | 'desc'
  page?: number
  page_size?: number
}): Promise<SessionListResponse> {
  const searchParams = new URLSearchParams()
  if (params?.project_id) searchParams.set('project_id', params.project_id)
  if (params?.status) searchParams.set('status', params.status)
  if (params?.agent_slug) searchParams.set('agent_slug', params.agent_slug)
  if (params?.session_type)
    searchParams.set('session_type', params.session_type)
  if (params?.parent_session_id)
    searchParams.set('parent_session_id', params.parent_session_id)
  if (params?.external_id) searchParams.set('external_id', params.external_id)
  if (params?.sort_by) searchParams.set('sort_by', params.sort_by)
  if (params?.sort_direction)
    searchParams.set('sort_direction', params.sort_direction)
  if (params?.page) searchParams.set('page', params.page.toString())
  if (params?.page_size)
    searchParams.set('page_size', params.page_size.toString())

  const url = searchParams.toString()
    ? `${API_BASE}/sessions?${searchParams}`
    : `${API_BASE}/sessions`

  const response = await fetchApi(url)
  if (!response.ok) {
    throw new Error(`Sessions fetch failed: ${response.status}`)
  }
  return response.json()
}

/** Callers say whether they need the events: they are the bulk of a long session's detail. */
export async function fetchSession(
  id: string,
  options: { includeEvents: boolean },
): Promise<Session> {
  const response = await fetchApi(
    `${API_BASE}/sessions/${id}?include_events=${options.includeEvents}`,
  )
  if (!response.ok) {
    throw new Error(`Session fetch failed: ${response.status}`)
  }
  return response.json()
}

export async function cancelSessionStream(
  sessionId: string,
): Promise<{ cancelled: boolean; session_id: string }> {
  const response = await fetchApi(`${API_BASE}/complete/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  })
  if (!response.ok) {
    throw new Error(`Session stream cancel failed: ${response.status}`)
  }
  return response.json()
}

export async function closeSession(
  sessionId: string,
): Promise<{ id: string; status: string; message: string }> {
  const response = await fetchApi(`${API_BASE}/sessions/${sessionId}/close`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`Session close failed: ${response.status}`)
  }
  return response.json()
}

export async function fetchSessionEvents(
  sessionId: string,
  params?: {
    event_type?: string
    turn?: number
    page?: number
    page_size?: number
    snapshot?: string
    exclude_types?: readonly string[]
    q?: string
    after?: string
    order?: 'asc' | 'desc'
  },
): Promise<SessionEventsResponse> {
  const searchParams = new URLSearchParams()
  if (params?.event_type) searchParams.set('event_type', params.event_type)
  if (params?.exclude_types?.length)
    searchParams.set('exclude_types', params.exclude_types.join(','))
  if (params?.q) searchParams.set('q', params.q)
  if (params?.after) searchParams.set('after', params.after)
  if (params?.order) searchParams.set('order', params.order)
  if (params?.turn !== undefined)
    searchParams.set('turn', params.turn.toString())
  if (params?.page) searchParams.set('page', params.page.toString())
  if (params?.page_size)
    searchParams.set('page_size', params.page_size.toString())
  if (params?.snapshot) searchParams.set('snapshot', params.snapshot)

  const url = searchParams.toString()
    ? `${API_BASE}/sessions/${sessionId}/events?${searchParams}`
    : `${API_BASE}/sessions/${sessionId}/events`

  const response = await fetchApi(url)
  if (!response.ok) {
    throw new Error(`Session events fetch failed: ${response.status}`)
  }
  return response.json()
}

export async function fetchAllSessionEvents(
  sessionId: string,
  params?: {
    event_type?: string
    turn?: number
    page_size?: number
    max_pages?: number
  },
): Promise<SessionEventsResponse> {
  const pageSize = Math.min(
    params?.page_size ?? SESSION_EVENTS_MAX_PAGE_SIZE,
    SESSION_EVENTS_MAX_PAGE_SIZE,
  )
  const maxPages = params?.max_pages ?? 100
  const firstPage = await fetchSessionEvents(sessionId, {
    event_type: params?.event_type,
    turn: params?.turn,
    page: 1,
    page_size: pageSize,
  })

  if (
    firstPage.events.length >= firstPage.total ||
    firstPage.events.length === 0
  ) {
    return firstPage
  }

  const allEvents = [...firstPage.events]
  let maxTurn = firstPage.max_turn

  for (
    let page = 2;
    page <= maxPages && allEvents.length < firstPage.total;
    page += 1
  ) {
    const nextPage = await fetchSessionEvents(sessionId, {
      event_type: params?.event_type,
      turn: params?.turn,
      page,
      page_size: pageSize,
      snapshot: firstPage.snapshot,
    })
    if (nextPage.events.length === 0) {
      break
    }
    allEvents.push(...nextPage.events)
    maxTurn = Math.max(maxTurn, nextPage.max_turn)
  }

  return {
    session_id: firstPage.session_id,
    events: allEvents,
    total: firstPage.total,
    max_turn: maxTurn,
    snapshot: firstPage.snapshot,
  }
}

/** When Agent Hub treats a quiet session as dead and closes it. */
export interface SessionCloseSettings {
  dead_candidate_after_minutes: number
  reapable_after_minutes: number
  zero_event_close_after_minutes: number
  transcript_sync_close_after_minutes: number
  completion_close_after_minutes: number
  any_session_close_after_minutes: number
  codex_close_inactive_enabled: boolean
  codex_scan_hours: number
  updated_by?: string | null
}

async function closeSettingsError(response: Response): Promise<Error> {
  const body = await response.json().catch(() => null)
  const detail = body?.detail
  if (typeof detail === 'string') return new Error(detail)
  if (Array.isArray(detail) && typeof detail[0]?.msg === 'string')
    return new Error(detail[0].msg)
  return new Error(`Request failed (${response.status})`)
}

export async function fetchSessionCloseSettings(): Promise<SessionCloseSettings> {
  const response = await fetchApi(`${API_BASE}/sessions/close-settings`)
  if (!response.ok) throw await closeSettingsError(response)
  return response.json()
}

export async function updateSessionCloseSettings(
  changes: Partial<SessionCloseSettings>,
): Promise<SessionCloseSettings> {
  const response = await fetchApi(`${API_BASE}/sessions/close-settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  })
  if (!response.ok) throw await closeSettingsError(response)
  return response.json()
}
