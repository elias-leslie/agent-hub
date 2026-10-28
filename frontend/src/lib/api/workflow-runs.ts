/**
 * Workflow runs: list, detail (steps, attempts, requested vs served model) and owner resume.
 */

import { fetchApi, getApiBaseUrl } from '../api-config'

const API_BASE = `${getApiBaseUrl()}/api`

export type RunState =
  | 'running'
  | 'needs_owner'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface WorkflowRunListItem {
  id: string
  state: RunState | null
  goal: string | null
  project_id: string | null
  pause_reason: string | null
  failure: string | null
  created_at: string | null
  last_activity_at: string | null
  step_total: number
  step_counts: Record<string, number>
  attempt_count: number
  /** Attempts that ended in a refusal, substitution, usage limit or interruption. */
  flagged_attempts: number
  served_models: string[]
  /** null when no attempt reported it (unknown is not zero). */
  total_tokens: number | null
  cost: CostTotals
}

/** What a cost figure means: cash billed per token, the list-price value of subscription work, or unclassified. */
export type CostBasis = 'metered' | 'subscription_equiv' | 'unknown'

export interface BasisTotal {
  /** null when no attempt on this basis had a price (unknown is not zero). */
  usd: number | null
  attempts: number
  /** Attempts that used tokens but could not be priced. */
  unpriced_attempts: number
}

/** Cost over a run's attempts, split by basis; bases are never summed together. */
export interface CostTotals {
  by_basis: Record<CostBasis, BasisTotal>
  unpriced_attempts: number
  /** Priced attempts whose figure is a catalog estimate rather than a provider-reported cost. */
  estimated_attempts: number
}

export interface UsageTotals {
  total_tokens: number | null
  cost: CostTotals
}

export interface AttemptCost {
  usd: number | null
  basis: CostBasis
  source: 'provider_reported' | 'catalog_estimate' | null
}

export interface WorkflowRunList {
  runs: WorkflowRunListItem[]
  total: number
  limit: number
  offset: number
}

/** Provider outcome of an attempt (outcome_details); only populated fields are present. */
export interface AttemptOutcome {
  kind: 'refused' | 'substituted' | 'usage_limit' | 'interrupted' | 'cancelled'
  requested_model: string
  served_model?: string
  category?: string
  explanation?: string
  window?: string
  resets_at?: number
  request_id?: string
}

export interface AttemptUsage {
  input_tokens?: number
  cache_read_tokens?: number
  cache_write_tokens?: number
  output_tokens?: number
  reasoning_tokens?: number
  total_tokens?: number
  cost_usd?: number | null
  cost_basis?: CostBasis
  cost_source?: AttemptCost['source']
  total_cost_usd?: number
  /** Fraction (0-1) of each subscription window used, when the provider reported it. */
  rate_limit_windows?: Record<string, number>
  duration_ms?: number
}

export interface Hop {
  from_model: string
  to_model: string
  category: string | null
  kind: string
}

/** One acceptance command the runner ran after the executor finished (exit 0 passes). */
export interface AcceptanceResult {
  cmd: string
  /** null when the command timed out or could not start. */
  exit_code: number | null
  timed_out: boolean
  duration_s: number
  output_tail: string
  passed: boolean
}

export interface AcceptanceCommand {
  cmd: string
  timeout_s: number | null
}

/** The caps the runner enforces; each is a per-step count unless noted. */
export interface RunLimits {
  max_total_attempts: number
  /** Waits in a row that made no progress before the run pauses for the owner. */
  max_unproductive_usage_limit_resumes: number
  acceptance_retry_limit: number
  restart_limit: number
  /** Refusals per category across the whole run. */
  refusal_pause_threshold: number
}

/** Who asked for a stop, when, and why; stored with the run or the step. */
export interface CancelRecord {
  scope: 'run' | 'step'
  reason: string | null
  requested_by: string | null
  request_source?: string | null
  /** Unix seconds. */
  requested_at: number
}

/** A harness process the attempt started; recovery says what it did to it after a crash. */
export interface AttemptProcess {
  kind: string
  pid: number
  pgid: number
  recovery?: string | null
}

export interface WorkflowAttempt {
  session_id: string
  attempt: number
  status: string
  requested_model: string | null
  effective_model: string | null
  served_model: string | null
  fallback_used: boolean | null
  fallback_reason: string | null
  served_models: string[]
  hop_from: Hop | null
  next_hop: Hop | null
  outcome: AttemptOutcome | null
  usage: AttemptUsage | null
  /** Cost with its basis, from the server; absent on older responses. */
  cost?: AttemptCost
  error: string | null
  decision: { action: string; reason: string } | null
  native_session_id: string | null
  transcript_path: string | null
  context_status: string | null
  /** null when the step has no acceptance commands (or the attempt never got that far). */
  acceptance?: AcceptanceResult[] | null
  /** Processes the attempt started (harness, acceptance commands); absent on older responses. */
  processes?: AttemptProcess[]
  executor: string | null
  started_at: string | null
  finished_at: string | null
}

export interface Handoff {
  summary?: string
  decisions?: string[]
  files?: string[]
  open_questions?: string[]
}

export type StepStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'refused'
  | 'needs_owner'
  | 'skipped'
  | 'cancelled'

export interface ExtraAttempts {
  total: number
  grants: {
    count: number
    requested_by: string | null
    request_source: string | null
    requested_at: number
    note: string | null
  }[]
}

/** Display-only liveness of the running attempt, saved at the heartbeat rate. */
export interface StepLive {
  /** thinking, writing, waiting, provider_retry or tool:<name>. */
  phase: string | null
  last_event_at: string | null
  /** null when the work runs inside the service (no child process). */
  harness_pid: number | null
  harness_alive: boolean | null
  updated_at: string | null
}

/** Where a not-yet-started step stands against its dependencies. */
export interface StepReadiness {
  state: 'ready' | 'waiting' | 'blocked'
  /** Dependencies that have not finished and may still complete. */
  waiting_on: string[]
  /** Dependencies that ended without completing (skipped, cancelled, failed), so this step cannot start. */
  blocked_by: { key: string; status: StepStatus }[]
  reason: string | null
}

export interface WorkflowStepView {
  key: string
  position: number
  status: StepStatus
  agent_slug: string
  /** Steps this one waits for; their handoffs are its context. Empty for a step that depends on nothing. */
  depends_on?: string[]
  /** False when the list is the default (the step before it). */
  depends_on_explicit?: boolean
  /** Only for steps that have not started. */
  readiness?: StepReadiness | null
  chain: string[] | null
  attempts: number
  /** Most attempts the step may use (the run cap, lowered by the step's own max_attempts). */
  attempt_limit?: number
  restarts: number
  usage_limit_resumes?: number
  /** Resumes in a row since the step last made progress; the pause counts these. */
  unproductive_resumes?: number
  /** Attempts the owner added to this step's cap, with who asked. */
  extra_attempts?: ExtraAttempts | null
  /** What the running step is doing now; null when it reports nothing yet. */
  live?: StepLive | null
  acceptance_failures?: number
  acceptance?: AcceptanceCommand[]
  /** The step's own thinking-level override; null when the agent's applies. */
  effort?: string | null
  chosen_model: string | null
  answered_by: string[] | null
  hops: Hop[]
  checkpoint_sha: string | null
  handoff: Handoff | null
  owner_decision: {
    action: string
    model?: string | null
    note?: string | null
    extra_attempts?: number | null
  } | null
  /** The stop request for this step, if one was made. */
  cancel?: CancelRecord | null
  /** The request is made and the worker has not yet stopped the step. */
  cancelling?: boolean
  heartbeat_at: string | null
  attempt_history: WorkflowAttempt[]
}

export interface RunPause {
  reason: string
  step_key?: string
  /** For a run blocked on dependencies: each blocked step and what blocks it. */
  blocked?: Record<string, StepReadiness>
  category?: string | null
  /** Unix seconds; a usage-limit pause resumes by itself after this. */
  resume_after?: number | null
  error?: string
  at?: number
}

/** One field-level change in the plan history; `before` is null for an added step, `after` for a removed one. */
export interface PlanChangeRecord {
  step: string
  op: 'add' | 'revise' | 'remove'
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
}

export interface PlanHistoryEntry {
  revision: number
  /** Unix seconds. */
  at: number
  action: 'add_steps' | 'revise_step' | 'remove_step'
  by: {
    changed_by?: string | null
    client_id?: string | null
    request_source?: string | null
  }
  reason?: string | null
  changes: PlanChangeRecord[]
  relinked?: string[]
}

export interface WorkflowRunDetail {
  id: string
  state: RunState | null
  goal: string | null
  project_id: string | null
  task_id: string | null
  repo_path: string | null
  branch: string | null
  pause: RunPause | null
  failure: string | null
  /** The stop request for the whole run, if one was made. */
  cancel?: CancelRecord | null
  /** The request is made and the worker has not yet stopped the running step. */
  cancelling?: boolean
  refusals: Record<string, number>
  /** Opaque id of whatever started the run (e.g. an Aico session) and an optional label for the coordinator. */
  launched_by?: string | null
  coordinator?: string | null
  /** 0 until the plan is revised; each added, changed or removed step set bumps it. */
  plan_revision?: number
  plan_history?: PlanHistoryEntry[]
  limits?: RunLimits
  created_at: string | null
  last_activity_at: string | null
  steps: WorkflowStepView[]
  /** Tokens and cost over every attempt, cost split by basis. */
  usage_totals?: UsageTotals
}

export type ResumeAction = 'retry' | 'skip' | 'fail'

async function failure(response: Response, what: string): Promise<Error> {
  let detail = ''
  try {
    const body = await response.json()
    detail =
      body?.detail?.message ??
      (typeof body?.detail === 'string' ? body.detail : '')
  } catch {
    // body is not JSON; the status is enough
  }
  return new Error(`${what} (${response.status})${detail ? `: ${detail}` : ''}`)
}

export async function fetchWorkflowRuns(
  params: { limit: number; offset: number },
  signal?: AbortSignal,
): Promise<WorkflowRunList> {
  const query = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  })
  const response = await fetchApi(`${API_BASE}/workflow-runs?${query}`, {
    signal,
  })
  if (!response.ok)
    throw await failure(response, 'Workflow runs request failed')
  return response.json()
}

export async function fetchWorkflowRun(
  id: string,
  signal?: AbortSignal,
): Promise<WorkflowRunDetail> {
  const response = await fetchApi(
    `${API_BASE}/workflow-runs/${encodeURIComponent(id)}`,
    {
      signal,
    },
  )
  if (response.status === 404) throw new Error('Run not found (404)')
  if (!response.ok) throw await failure(response, 'Workflow run request failed')
  return response.json()
}

export async function resumeWorkflowRun(
  id: string,
  decision: {
    action: ResumeAction
    step_key?: string
    model?: string | null
    /** Retry only: attempts to add to this step's cap. */
    extra_attempts?: number
  },
): Promise<{ run_id: string; state: RunState; step: string; status: string }> {
  const response = await fetchApi(
    `${API_BASE}/workflow-runs/${encodeURIComponent(id)}/resume`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(decision),
    },
  )
  if (!response.ok) throw await failure(response, 'Resume failed')
  return response.json()
}

export interface CancelResult {
  run_id: string
  state: RunState
  step?: string
  status?: string
  cancel: CancelRecord
  cancelling: boolean
}

async function postCancel(
  path: string,
  reason: string | undefined,
): Promise<CancelResult> {
  const response = await fetchApi(`${API_BASE}/workflow-runs/${path}/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(reason ? { reason } : {}),
  })
  if (!response.ok) throw await failure(response, 'Cancel failed')
  return response.json()
}

/** Stop the whole run; a running step is stopped by its worker within a few seconds. */
export function cancelWorkflowRun(
  id: string,
  reason?: string,
): Promise<CancelResult> {
  return postCancel(encodeURIComponent(id), reason)
}

/** Stop one step; the run goes on with the others. */
export function cancelWorkflowStep(
  id: string,
  stepKey: string,
  reason?: string,
): Promise<CancelResult> {
  return postCancel(
    `${encodeURIComponent(id)}/steps/${encodeURIComponent(stepKey)}`,
    reason,
  )
}
