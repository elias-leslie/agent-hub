import type {
  RunPause,
  RunState,
  StepStatus,
  WorkflowAttempt,
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
}

export const STATE_TONE: Record<string, { dot: string; text: string }> = {
  running: { dot: 'bg-sky-400', text: 'text-sky-300' },
  pending: { dot: 'bg-slate-500', text: 'text-slate-400' },
  needs_owner: { dot: 'bg-amber-400', text: 'text-amber-300' },
  completed: { dot: 'bg-emerald-400', text: 'text-emerald-300' },
  failed: { dot: 'bg-rose-400', text: 'text-rose-300' },
  refused: { dot: 'bg-rose-400', text: 'text-rose-300' },
  skipped: { dot: 'bg-slate-500', text: 'text-slate-400' },
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
    case 'owner_only_category':
      return `${step} was refused${category}. This category is yours to route, so the run stopped.`
    case 'refusal_threshold':
      return `Too many refusals${category} in this run. ${step} is paused for your decision.`
    case 'no_agent_route':
      return `${step} has no model route to run on${pause.error ? `: ${pause.error}` : '.'}`
    default:
      return `${step} is paused: ${pause.reason.replaceAll('_', ' ')}.`
  }
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

export function attemptCost(attempt: WorkflowAttempt): number | null {
  const usage = attempt.usage
  return usage?.cost_usd ?? usage?.total_cost_usd ?? null
}

/** Wall-clock span of an attempt; null when it has not finished or timestamps are missing. */
export function attemptDurationMs(attempt: WorkflowAttempt): number | null {
  if (!attempt.started_at || !attempt.finished_at) return null
  const ms =
    new Date(attempt.finished_at).getTime() -
    new Date(attempt.started_at).getTime()
  return Number.isFinite(ms) && ms >= 0 ? ms : null
}
