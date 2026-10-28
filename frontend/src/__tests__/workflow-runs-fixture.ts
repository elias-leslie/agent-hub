import type {
  CostBasis,
  CostTotals,
  WorkflowAttempt,
  WorkflowRunDetail,
  WorkflowRunListItem,
  WorkflowStepView,
} from '@/lib/api/workflow-runs'

export const OPUS_55 = 'claude-opus-5-5'
export const OPUS_48 = 'claude-opus-4-8'
export const CODEX = 'codex/gpt-5.6-sol-daybreak-blue'

export function attempt(
  overrides: Partial<WorkflowAttempt> = {},
): WorkflowAttempt {
  return {
    session_id: 'a1111111-0000-0000-0000-000000000000',
    attempt: 1,
    status: 'completed',
    requested_model: OPUS_55,
    effective_model: OPUS_55,
    served_model: OPUS_55,
    fallback_used: false,
    fallback_reason: null,
    served_models: [OPUS_55],
    hop_from: null,
    next_hop: null,
    outcome: null,
    usage: { total_tokens: 1200, cost_usd: 0.0123 },
    error: null,
    decision: { action: 'complete', reason: 'completed' },
    native_session_id: null,
    transcript_path: '/tmp/runs/r1/run/plan.jsonl',
    context_status: 'ok',
    executor: 'claude_code',
    started_at: '2026-10-28T10:00:00Z',
    finished_at: '2026-10-28T10:00:42Z',
    ...overrides,
  }
}

export function step(
  overrides: Partial<WorkflowStepView> = {},
): WorkflowStepView {
  return {
    key: 'plan',
    position: 0,
    status: 'completed',
    agent_slug: 'planner',
    chain: [OPUS_55, CODEX, OPUS_48],
    attempts: 1,
    attempt_limit: 12,
    restarts: 0,
    usage_limit_resumes: 0,
    acceptance_failures: 0,
    acceptance: [],
    effort: null,
    chosen_model: OPUS_55,
    answered_by: [OPUS_55],
    hops: [],
    checkpoint_sha: 'abc123',
    handoff: {
      summary: 'Planned the export change in two files.',
      decisions: ['keep the CSV format'],
      files: ['export.py'],
      open_questions: [],
    },
    owner_decision: null,
    heartbeat_at: null,
    attempt_history: [attempt()],
    ...overrides,
  }
}

export function run(
  overrides: Partial<WorkflowRunDetail> = {},
): WorkflowRunDetail {
  return {
    id: 'r1111111-0000-0000-0000-000000000000',
    state: 'completed',
    goal: 'Add CSV export to the reports page',
    project_id: 'agent-hub',
    task_id: null,
    repo_path: null,
    branch: 'workflow/r1111111',
    pause: null,
    failure: null,
    refusals: {},
    limits: {
      max_total_attempts: 12,
      max_unproductive_usage_limit_resumes: 3,
      acceptance_retry_limit: 2,
      restart_limit: 2,
      refusal_pause_threshold: 12,
    },
    created_at: '2026-10-28T10:00:00Z',
    last_activity_at: '2026-10-28T10:05:00Z',
    steps: [step()],
    ...overrides,
  }
}

export function listItem(
  overrides: Partial<WorkflowRunListItem> = {},
): WorkflowRunListItem {
  return {
    id: 'r1111111-0000-0000-0000-000000000000',
    state: 'completed',
    goal: 'Add CSV export to the reports page',
    project_id: 'agent-hub',
    pause_reason: null,
    failure: null,
    created_at: '2026-10-28T10:00:00Z',
    last_activity_at: '2026-10-28T10:05:00Z',
    step_total: 4,
    step_counts: { completed: 4 },
    attempt_count: 5,
    flagged_attempts: 0,
    served_models: [OPUS_55],
    total_tokens: 6000,
    cost: costTotals({ subscription_equiv: 0.06 }),
    ...overrides,
  }
}

/** Cost totals with a price on the given bases; the others have no priced attempt. */
export function costTotals(
  priced: Partial<Record<CostBasis, number>> = {},
  unpriced = 0,
): CostTotals {
  const row = (basis: CostBasis) => ({
    usd: priced[basis] ?? null,
    attempts: priced[basis] === undefined ? 0 : 1,
    unpriced_attempts: basis === 'unknown' ? unpriced : 0,
  })
  return {
    by_basis: {
      metered: row('metered'),
      subscription_equiv: row('subscription_equiv'),
      unknown: row('unknown'),
    },
    unpriced_attempts: unpriced,
    estimated_attempts: 0,
  }
}
