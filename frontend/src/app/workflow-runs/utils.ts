import { formatCost } from '@/app/sessions/utils'
import type {
  AttemptCost,
  CancelRecord,
  CostBasis,
  CostTotals,
  PlanChangeRecord,
  PlanHistoryEntry,
  RunPause,
  RunResult,
  RunState,
  StepLive,
  StepStatus,
  StepWorkspace,
  WorkflowAttempt,
  WorkflowStepView,
} from '@/lib/api/workflow-runs'

const CLAUDE_FAMILY = /^(opus|sonnet|haiku|fable)-(\d+)-(\d+)(?:-\d{8})?$/i

/** "claude-opus-5-5" reads as "Opus 5.5"; any other id is shown as it is. */
export function modelLabel(model: string | null | undefined): string {
  if (!model) return 'unknown model'
  const bare = model.replace(/^claude-/, '')
  const match = CLAUDE_FAMILY.exec(bare)
  if (!match) return model
  const family = match[1]
  return `${family[0].toUpperCase()}${family.slice(1).toLowerCase()} ${match[2]}.${match[3]}`
}

const SNAPSHOT_SUFFIX = /-(?:\d{4}-\d{2}-\d{2}|\d{8})$/

function bare(model: string): string {
  return (
    model.trim().toLowerCase().split('/').pop()?.replace(SNAPSHOT_SUFFIX, '') ??
    ''
  )
}

/** Same rule as the backend: provider prefixes, case and dated snapshots are the same model. */
export function isModelSwitch(
  requested: string | null | undefined,
  served: string | null | undefined,
): boolean {
  if (!requested || !served) return false
  return bare(requested) !== bare(served)
}

export interface AttemptModels {
  /** The model this attempt was sent to. */
  asked: string | null
  /** The model that answered (last one the provider reported); null when the attempt got no answer. */
  answered: string | null
  /** The provider answered with a different model than it was asked. */
  substituted: boolean
}

export function attemptModels(attempt: WorkflowAttempt): AttemptModels {
  const asked = attempt.effective_model ?? attempt.requested_model
  const reported = attempt.outcome?.kind === 'substituted'
  // Only an attempt that finished (or was answered by a substitute) had an answer; a refused,
  // limited, interrupted or errored one has served_models only because the model was asked.
  const answeredAttempt = attempt.status === 'completed' || reported
  const answered = answeredAttempt
    ? (attempt.served_models.at(-1) ?? attempt.served_model ?? null)
    : null
  return {
    asked,
    answered,
    substituted: reported || isModelSwitch(asked, answered),
  }
}

export const RUN_STATE_LABEL: Record<RunState, string> = {
  running: 'Running',
  needs_owner: 'Needs you',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

export function runStateLabel(state: RunState | null): string {
  return state ? (RUN_STATE_LABEL[state] ?? state) : 'Unknown'
}

export const STEP_STATUS_LABEL: Record<StepStatus, string> = {
  pending: 'Waiting',
  running: 'Running',
  completed: 'Done',
  failed: 'Failed',
  refused: 'Refused',
  needs_owner: 'Needs you',
  skipped: 'Skipped',
  cancelled: 'Cancelled',
}

export const STATE_TONE: Record<string, { dot: string; text: string }> = {
  running: { dot: 'bg-sky-400', text: 'text-sky-300' },
  pending: { dot: 'bg-slate-500', text: 'text-slate-400' },
  needs_owner: { dot: 'bg-amber-400', text: 'text-amber-300' },
  completed: { dot: 'bg-emerald-400', text: 'text-emerald-300' },
  failed: { dot: 'bg-rose-400', text: 'text-rose-300' },
  refused: { dot: 'bg-rose-400', text: 'text-rose-300' },
  skipped: { dot: 'bg-slate-500', text: 'text-slate-400' },
  cancelled: { dot: 'bg-slate-400', text: 'text-slate-300' },
}

export const EXECUTOR_LABEL: Record<string, string> = {
  claude_code: 'Claude Code',
  codex: 'Codex',
  pi: 'Pi',
  agent_hub: 'Agent Hub',
  faux: 'Test executor',
}

export function executorLabel(kind: string | null): string {
  return kind ? (EXECUTOR_LABEL[kind] ?? kind) : 'executor not recorded'
}

/** The tool names an attempt was given, or null when its executor did not report them. */
export function attemptToolsText(attempt: WorkflowAttempt): string | null {
  const tools = attempt.tools
  if (!tools) return null
  return tools.length > 0 ? tools.join(', ') : 'none'
}

export function categoryText(category: string | null | undefined): string {
  return category ? ` (${category})` : ''
}

export function formatResetTime(
  epochSeconds: number | undefined,
): string | null {
  if (!epochSeconds) return null
  return new Date(epochSeconds * 1000).toLocaleString()
}

/** What the run is waiting on, in the owner's terms. */
export function pauseExplanation(
  pause: RunPause,
  stepKey: string | undefined,
): string {
  const step = stepKey ? `Step "${stepKey}"` : 'A step'
  const category = categoryText(pause.category)
  switch (pause.reason) {
    case 'chain_exhausted':
      return `${step} could not finish: every model in its chain was tried.`
    case 'usage_limit_wait': {
      const reset = formatResetTime(pause.resume_after ?? undefined)
      return `${step} is waiting for a usage limit to reset${reset ? ` at ${reset}` : ''}. It resumes by itself after that.`
    }
    case 'usage_limit_resume_limit':
      return `${step} has waited out its usage limit as many times as allowed. It is paused for your decision.`
    case 'owner_only_category':
      return `${step} was refused${category}. This category is yours to route, so the run stopped.`
    case 'refusal_threshold':
      return `Too many refusals${category} in this run. ${step} is paused for your decision.`
    case 'blocked_dependencies':
      return 'No step can start: the ones left wait on steps that were skipped, cancelled or failed. The plan needs a change from whoever coordinates the run, or you can cancel the run.'
    case 'step_failed': {
      const failed = Object.keys(pause.failed ?? {})
      const blocked = Object.keys(pause.blocked ?? {})
      const names = failed.length > 0 ? failed.join(', ') : 'a step'
      return `${failed.length === 1 ? 'Step' : 'Steps'} ${names} failed. Everything that did not depend on ${failed.length === 1 ? 'it' : 'them'} has finished${blocked.length > 0 ? `; ${blocked.join(', ')} cannot start` : ''}. Retry or skip ${stepKey ? `"${stepKey}"` : 'the step'}, change the plan, or end the run.`
    }
    case 'tools_unavailable':
      return `${step} needs shell and file-edit tools that its project's Agent Hub permission tier does not give it, and no other model in its chain could run it${pause.error ? `: ${pause.error}` : '.'}`
    case 'no_agent_route':
      return `${step} has no model route to run on${pause.error ? `: ${pause.error}` : '.'}`
    default:
      return `${step} is paused: ${pause.reason.replaceAll('_', ' ')}.`
  }
}

/** Who stopped a run or step, when, and why, in the owner's terms. */
export function cancelText(
  cancel: CancelRecord,
  what: 'run' | 'step',
  finished: boolean,
): string {
  const when = new Date(cancel.requested_at * 1000).toLocaleString()
  const who = cancel.requested_by ? ` by ${cancel.requested_by}` : ''
  const lead = finished
    ? `This ${what} was cancelled`
    : `Cancel requested for this ${what}`
  return `${lead}${who} at ${when}${cancel.reason ? `: ${cancel.reason}` : '.'}`
}

const TOKEN_PARTS = [
  'input_tokens',
  'cache_read_tokens',
  'cache_write_tokens',
  'output_tokens',
] as const

/** total_tokens when the executor reported it, else the sum of the parts it did report; null when unknown. */
export function attemptTokens(attempt: WorkflowAttempt): number | null {
  const usage = attempt.usage
  if (!usage) return null
  if (typeof usage.total_tokens === 'number') return usage.total_tokens
  const parts = TOKEN_PARTS.flatMap((key) =>
    typeof usage[key] === 'number' ? [usage[key] as number] : [],
  )
  return parts.length > 0 ? parts.reduce((a, b) => a + b, 0) : null
}

const BASIS_LABEL: Record<CostBasis, string> = {
  metered: 'metered',
  subscription_equiv: 'subscription equiv.',
  unknown: 'basis unknown',
}

export function basisLabel(basis: CostBasis): string {
  return BASIS_LABEL[basis]
}

/** The attempt's cost with its basis; usd is null when nothing could price it. */
export function attemptCost(attempt: WorkflowAttempt): AttemptCost | null {
  if (attempt.cost) return attempt.cost
  const usage = attempt.usage
  if (!usage) return null
  if (usage.cost_basis) {
    return {
      usd: usage.cost_usd ?? null,
      basis: usage.cost_basis,
      source: usage.cost_source ?? null,
    }
  }
  if (typeof usage.total_cost_usd === 'number') {
    return {
      usd: usage.total_cost_usd,
      basis: 'subscription_equiv',
      source: 'provider_reported',
    }
  }
  if (typeof usage.cost_usd === 'number') {
    return { usd: usage.cost_usd, basis: 'unknown', source: null }
  }
  return null
}

/** "$0.012 subscription equiv. (est.)", or "cost n/a" when it was not priced. */
export function attemptCostText(attempt: WorkflowAttempt): string {
  const cost = attemptCost(attempt)
  if (!cost || cost.usd === null) return 'cost n/a'
  const estimate = cost.source === 'catalog_estimate' ? ' (est.)' : ''
  return `${formatCost(cost.usd)} ${basisLabel(cost.basis)}${estimate}`
}

const BASIS_ORDER: CostBasis[] = ['metered', 'subscription_equiv', 'unknown']

/** One part per basis that has attempts, then the unpriced count; "cost n/a" when nothing was priced or used. */
export function costTotalsParts(cost: CostTotals): string[] {
  const parts: string[] = []
  for (const basis of BASIS_ORDER) {
    const row = cost.by_basis[basis]
    if (row.usd !== null) {
      parts.push(`${formatCost(row.usd)} ${basisLabel(basis)}`)
    }
  }
  if (cost.unpriced_attempts > 0) {
    parts.push(`${cost.unpriced_attempts} unpriced`)
  }
  if (cost.estimated_attempts > 0) {
    parts.push(`${cost.estimated_attempts} estimated`)
  }
  return parts.length > 0 ? parts : ['cost n/a']
}

/** Wall-clock span of an attempt; null when it has not finished or timestamps are missing. */
export function attemptDurationMs(attempt: WorkflowAttempt): number | null {
  if (!attempt.started_at || !attempt.finished_at) return null
  const ms =
    new Date(attempt.finished_at).getTime() -
    new Date(attempt.started_at).getTime()
  return Number.isFinite(ms) && ms >= 0 ? ms : null
}

/** "3 of 12" for a count against its cap; just the count when the cap is unknown. */
export function ofLimit(count: number, limit: number | undefined): string {
  return limit === undefined ? String(count) : `${count} of ${limit}`
}

/** A count that has used all of its cap is worth a second look. */
export function atLimit(count: number, limit: number | undefined): boolean {
  return limit !== undefined && limit > 0 && count >= limit
}

/** Seconds of silence in a saved status before the page says it may be out of date. */
const LIVE_STATUS_STALE_SECONDS = 120

export interface LiveStatusText {
  phase: string | null
  phaseText: string
  activityText: string
  process: 'alive' | 'gone' | 'inside' | 'unknown'
  processText: string
  staleText: string | null
}

function ageText(iso: string | null | undefined, now: number): string | null {
  if (!iso) return null
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return null
  const secs = Math.max(0, Math.floor((now - then) / 1000))
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m ago`
}

/** The running attempt's phase, last activity and process state in plain words; unknown is not idle. */
export function liveStatus(
  live: StepLive | null | undefined,
  now: number = Date.now(),
): LiveStatusText {
  if (!live) {
    return {
      phase: null,
      phaseText: 'Working',
      activityText: 'no live status reported yet',
      process: 'unknown',
      processText: 'process state unknown',
      staleText: null,
    }
  }
  const phase = live.phase
  let phaseText = 'Working'
  if (phase === 'thinking') phaseText = 'Thinking'
  else if (phase === 'writing') phaseText = 'Writing'
  else if (phase === 'waiting') phaseText = 'Waiting on the model'
  else if (phase === 'provider_retry') phaseText = 'Provider retrying'
  else if (phase?.startsWith('tool:'))
    phaseText = `Running tool ${phase.slice('tool:'.length)}`
  const seen = ageText(live.last_event_at, now)
  let process: LiveStatusText['process'] = 'unknown'
  let processText = 'process state unknown'
  if (live.harness_pid === null && live.harness_alive === null) {
    process = 'inside'
    processText = 'no child process'
  } else if (live.harness_alive === true) {
    process = 'alive'
    processText = 'process alive'
  } else if (live.harness_alive === false) {
    process = 'gone'
    processText = 'process not found'
  }
  const saved = ageText(live.updated_at, now)
  const savedSecs = live.updated_at
    ? (now - new Date(live.updated_at).getTime()) / 1000
    : null
  return {
    phase,
    phaseText,
    activityText: seen ? `last activity ${seen}` : 'no activity seen yet',
    process,
    processText,
    staleText:
      savedSecs !== null && savedSecs > LIVE_STATUS_STALE_SECONDS
        ? `status saved ${saved}`
        : null,
  }
}

/** "Depends on plan, implement", "Depends on nothing", or the default ("follows plan") when none was declared. */
export function dependsText(step: WorkflowStepView): string | null {
  if (!step.depends_on) return null
  if (step.depends_on.length === 0) return 'Depends on nothing'
  const list = step.depends_on.join(', ')
  return step.depends_on_explicit === false
    ? `Follows ${list}`
    : `Depends on ${list}`
}

function shown(value: unknown): string {
  if (value === null || value === undefined) return 'none'
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > 80 ? `${text.slice(0, 77)}...` : text
}

/** One plan change in the owner's terms: "added c", "b: model_override none -> x", "removed b". */
export function planChangeText(change: PlanChangeRecord): string {
  if (change.op === 'add') return `added ${change.step}`
  if (change.op === 'remove') return `removed ${change.step}`
  const fields = Object.keys(change.after ?? {})
  const parts = fields.map(
    (field) =>
      `${field} ${shown(change.before?.[field])} -> ${shown(change.after?.[field])}`,
  )
  return `${change.step ?? 'run'}: ${parts.join('; ')}`
}

/** Who made a plan revision: the caller's own label first, then the client that sent it. */
export function planAuthor(by: PlanHistoryEntry['by']): string {
  return by.changed_by || by.client_id || by.request_source || 'unknown'
}

/** The merge that made a lane's start: "clean merge of a, b", "conflict in shared.txt", or nothing to merge. */
export function mergeText(workspace: StepWorkspace): string | null {
  if (workspace.kind !== 'lane') return null
  const merges = workspace.merges ?? []
  const names = (result: string) =>
    merges
      .filter((m) => m.result === result)
      .map((m) => m.step ?? m.sha.slice(0, 8))
  switch (workspace.merge_result) {
    case 'conflict': {
      const files = workspace.conflict_files ?? []
      return `Merge conflict in ${files.length > 0 ? files.join(', ') : 'some files'}; this step resolves it first`
    }
    case 'pending': {
      return `Merge of ${names('pending').join(', ')} still to do`
    }
    case 'clean':
      return `Clean merge of ${names('clean').join(', ')}`
    case 'up_to_date':
      return 'Dependencies already included; nothing to merge'
    default:
      return 'Started from its dependency, no merge needed'
  }
}

/** Where the run's code is, in plain words; null while a lane run is still going. */
export function resultText(
  result: RunResult | null | undefined,
): string | null {
  if (!result || !result.state) return null
  const where = `${result.branch ?? 'unknown branch'}${result.sha ? ` at ${result.sha.slice(0, 8)}` : ''}`
  if (result.state === 'conflict') {
    const left = (result.not_merged ?? []).join(', ')
    const files = (result.conflict_files ?? []).join(', ')
    return `Branches ${left || 'some'} could not be merged (conflict in ${files || 'some files'}); the rest is on ${where}`
  }
  return `Final code: ${where}`
}
