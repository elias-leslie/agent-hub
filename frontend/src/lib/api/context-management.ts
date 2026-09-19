import { fetchApi } from '@/lib/api-config'

export interface ContextPolicy {
  scope: 'global' | 'project' | 'agent' | 'unassigned'
  targets: string[]
  workflows: string[]
  activation: 'always' | 'triggered' | 'on_demand' | 'relevant'
  task_types: string[]
  phases: string[]
  applicability: Record<string, string[]>
  required: boolean
  format: 'full' | 'compact' | 'summary'
}
export interface ContextSelection {
  consumer_surface: string
  consumer_profile: string
  project_id: string | null
  agent_slug?: string | null
  capabilities: string[]
  workflow_ids: string[]
  requested_source_ids: string[]
  query: string
  task_type?: string | null
  phase?: string | null
  session_id?: string | null
}
export interface ContextSource {
  source_type: 'prompt' | 'memory' | 'computed'
  source_id: string
  name: string
  content: string
  summary: string
  enabled: boolean
  policy: ContextPolicy | null
  owner_agent_id: number | null
  authority: string
  revision: string
  state: string
  reason: string
  tokens: number
  rendered: string | null
  review_status: string | null
}
export interface ContextDelivery {
  status: 'ok' | 'failed'
  rendered: string
  estimated_tokens: number
  delivery_id: string
  failure?: { error_message: string } | null
}
export interface SourceEdit {
  source_type: 'prompt' | 'memory'
  source_id: string
  expected_revision: string
  name?: string
  content?: string
  summary?: string
  enabled?: boolean
  policy?: ContextPolicy
  archive?: boolean
}
export interface PlacementEdit {
  source_type: 'prompt' | 'memory'
  source_id: string
  mode: 'include' | 'exclude' | 'inherit'
}
export interface ContextDraft {
  context: ContextSelection
  edits: SourceEdit[]
  placements: PlacementEdit[]
  expected_placement_revision: string
  reason: string
  proposal_id?: string
}
export interface ContextInventory {
  profiles?: string[]
  sources: ContextSource[]
  delivery: ContextDelivery
  placement_revision: string
  placements: PlacementEdit[]
  placement_warnings?: (PlacementEdit & { reason: string })[]
  baseline?: ContextDelivery
  token_delta?: number
  checks?: ContextFinding[]
  change_id?: string
}
export interface ContextRecord {
  id: string
  kind: string
  actor: string
  created_at: string
  payload: Record<string, unknown>
}
export interface ContextFinding {
  kind: string
  source_ids: string[]
  passages: Record<string, string>
  explanation: string
  uncertainty: string
  remedy: string
  proposed_edits?: SourceEdit[]
}
export interface ContextReview {
  findings: ContextFinding[]
  estimated_input_tokens: number
  review_id?: string
  failure?: string
  reason?: string
  coverage: {
    eligible_sources: number
    candidate_pairs: number
    native: string
    candidate_method: string
  }
  screening?: {
    cache_hits: number
    new_calls: number
    estimated_new_input_tokens: number
    estimated_new_cost_usd: number
    actual_new_cost_usd?: number
    qualification: string
    entries?: { pair: string[]; status: string; result: unknown }[]
  }
}
export interface ContextMaintenanceItem {
  id: string
  version: number
  kind: string
  state: string
  summary: string
  recommendation: string
  source_keys: string[]
  handoff_needed: boolean
  claim_owner: string | null
  updated_at: string
  technical_work?: {
    task_id?: string
    status?: string
    [key: string]: unknown
  } | null
  decision: {
    question?: string
    recommendation?: string
    options?: string[]
    answer?: string
    reported?: boolean
  }
  detail?: {
    finding?: { passages: Record<string, string>; uncertainty: string }
    failure?: string
    background_reason?: string
  }
}

export interface ContextMaintenanceHealth {
  state:
    | 'healthy'
    | 'working'
    | 'needs_attention'
    | 'awaiting_owner'
    | 'unverified'
  scope: 'system'
  active_counts: Record<string, number>
  unresolved_failures: number
  technical_work: number
  technical_blocked: number
  last_successful_review_at: string | null
  last_memory_run: {
    id: string
    status: string
    reviewed: number
    failed: number
    completed_at: string | null
  } | null
  schedule_enabled: boolean
  next_run_at: string | null
  verification: string
}

export interface ContextMaintenanceView {
  items: ContextMaintenanceItem[]
  health?: ContextMaintenanceHealth
}

export async function contextRequest<T>(
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetchApi(
    `/api/runtime-context/manage${path}`,
    body === undefined
      ? undefined
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
  )
  if (!response.ok) {
    const error: { detail?: unknown } = await response.json().catch(() => ({}))
    throw new Error(
      typeof error.detail === 'string'
        ? error.detail
        : `Context request failed (${response.status})`,
    )
  }
  return response.json() as Promise<T>
}
