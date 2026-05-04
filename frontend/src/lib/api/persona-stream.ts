import { fetchApi } from '@/lib/api-config'

export interface PersonaStreamEventPreview {
  id: string
  event_type: string
  created_at: string
  role: string | null
  tool_name: string | null
  content_preview: string | null
  tool_input_preview: string | null
  tool_output_preview: string | null
  duration_ms: number | null
  model_used: string | null
}

export interface PersonaIssueMarker {
  event_id: string
  event_type: string
  created_at: string
  tool_name: string | null
  tags: string[]
  primary_tag: string
  root_causes: string[]
  primary_root_cause: string | null
  title: string
  summary: string
  detail: string | null
  fingerprint: string | null
}

export interface PersonaStreamEntry {
  id: string
  entry_type: 'message' | 'heartbeat' | 'child_run'
  timestamp: string
  session_id: string
  parent_session_id: string | null
  project_id: string
  agent_slug: string | null
  session_type: string
  status: string
  role: 'user' | 'assistant' | 'system' | null
  content: string | null
  summary_oneliner: string | null
  display_summary: string | null
  current_branch: string | null
  external_id: string | null
  model: string | null
  live_summary: string | null
  live_status: string | null
  live_topic: string | null
  message_count: number
  tool_count: number
  event_previews: PersonaStreamEventPreview[]
  issue_markers: PersonaIssueMarker[]
  pulse_tags: string[]
  primary_pulse_tag: string | null
  root_causes: string[]
  primary_root_cause: string | null
  pulse_summary: string | null
}

export interface PersonaStreamResponse {
  entries: PersonaStreamEntry[]
  total: number
  page: number
  page_size: number
  matches: PersonaStreamMatch[]
  match_count: number
  pulse: PersonaPulseSummary
}

export interface PersonaStreamMatch {
  entry_id: string
  session_id: string
  entry_type: 'message' | 'heartbeat' | 'child_run'
  timestamp: string
  snippet: string
}

export interface PersonaPulseMetric {
  key: string
  label: string
  count: number
  description: string
}

export interface PersonaIssueGroup {
  fingerprint: string
  title: string
  summary: string
  count: number
  primary_tag: string
  root_cause: string | null
  agent_slugs: string[]
  latest_entry_id: string | null
  latest_session_id: string | null
  latest_timestamp: string | null
}

export interface PersonaAgentScorecard {
  agent_slug: string
  label: string
  session_count: number
  success_count: number
  friction_count: number
  error_count: number
  recovered_count: number
  stalled_count: number
  instruction_drift_count: number
  tool_friction_count: number
  median_runtime_seconds: number | null
  top_issue: string | null
  top_root_cause: string | null
}

export interface PersonaPulseSummary {
  metrics: PersonaPulseMetric[]
  issue_groups: PersonaIssueGroup[]
  agent_scorecards: PersonaAgentScorecard[]
}

interface FetchPersonaStreamParams {
  timeRange: string
  search?: string
  focusSessionId?: string | null
  anchorEntryId?: string | null
  page?: number
  pageSize?: number
}

export async function fetchPersonaStream(
  params: FetchPersonaStreamParams,
): Promise<PersonaStreamResponse> {
  const searchParams = new URLSearchParams()
  searchParams.set('time_range', params.timeRange)
  searchParams.set('page', String(params.page ?? 1))
  searchParams.set('page_size', String(params.pageSize ?? 100))
  if (params.search) {
    searchParams.set('search', params.search)
  }
  if (params.focusSessionId) {
    searchParams.set('focus_session_id', params.focusSessionId)
  }
  if (params.anchorEntryId) {
    searchParams.set('anchor_entry_id', params.anchorEntryId)
  }

  const response = await fetchApi(
    `/api/persona/stream?${searchParams.toString()}`,
  )
  if (!response.ok) {
    throw new Error(`Persona stream fetch failed: ${response.status}`)
  }
  return response.json()
}
