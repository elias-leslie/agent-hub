import { formatRelativeTime } from '@/app/sessions/utils'
import type { RunLimits, WorkflowStepView } from '@/lib/api/workflow-runs'
import { cn } from '@/lib/utils'
import {
  atLimit,
  cancelText,
  dependsText,
  liveStatus,
  mergeText,
  modelLabel,
  ofLimit,
  STEP_STATUS_LABEL,
} from '../utils'
import { AttemptCard } from './AttemptCard'
import { CancelButton } from './CancelButton'
import { StatusDot } from './StatusDot'

function HandoffNote({ step }: { step: WorkflowStepView }) {
  const note = step.handoff
  if (!note) return null
  const lists: [string, string[] | undefined][] = [
    ['Decisions', note.decisions],
    ['Files', note.files],
    ['Open questions', note.open_questions],
  ]
  const extra = lists.filter(([, items]) => items && items.length > 0)
  return (
    <div className="mt-3 rounded-md border border-slate-800 bg-slate-900/40 p-3 text-[13px]">
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
        Handoff note
      </p>
      <p className="mt-1 whitespace-pre-wrap break-words text-slate-200">
        {note.summary ?? 'The step ended without a summary.'}
      </p>
      {extra.length > 0 ? (
        <details className="mt-2 text-[12px] text-slate-400">
          <summary className="cursor-pointer text-slate-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50">
            Details
          </summary>
          {extra.map(([title, items]) => (
            <div key={title} className="mt-1.5">
              <p className="font-medium text-slate-300">{title}</p>
              <ul className="list-disc pl-5">
                {items?.map((item) => (
                  <li key={item} className="break-words">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </details>
      ) : null}
    </div>
  )
}

/** Attempts and retries against the caps the runner enforces, so a loop that stops is not a surprise. */
function LimitLine({
  step,
  limits,
}: {
  step: WorkflowStepView
  limits: RunLimits | undefined
}) {
  const parts: { text: string; hot: boolean }[] = [
    {
      text: `Attempt ${ofLimit(step.attempts, step.attempt_limit)}`,
      hot: atLimit(step.attempts, step.attempt_limit),
    },
  ]
  const failures = step.acceptance_failures ?? 0
  if ((step.acceptance?.length ?? 0) > 0 || failures > 0) {
    parts.push({
      text: `acceptance retries ${ofLimit(failures, limits?.acceptance_retry_limit)}`,
      hot: atLimit(failures, limits?.acceptance_retry_limit),
    })
  }
  const resumes = step.usage_limit_resumes ?? 0
  if (resumes > 0) {
    // Only waits in a row with no new work count toward the pause.
    const idle = step.unproductive_resumes ?? resumes
    const cap = limits?.max_unproductive_usage_limit_resumes
    parts.push({
      text: `usage-limit resumes ${resumes}, idle in a row ${ofLimit(idle, cap)}`,
      hot: atLimit(idle, cap),
    })
  }
  const extra = step.extra_attempts
  if (extra && extra.total > 0) {
    const asked = extra.grants
      .map((g) => g.requested_by)
      .filter((who): who is string => Boolean(who))
    parts.push({
      text: `+${extra.total} attempts you added${asked.length > 0 ? ` (${[...new Set(asked)].join(', ')})` : ''}`,
      hot: false,
    })
  }
  if (step.restarts > 0) {
    parts.push({
      text: `restarts ${ofLimit(step.restarts, limits?.restart_limit)}`,
      hot: atLimit(step.restarts, limits?.restart_limit),
    })
  }
  if (step.effort) parts.push({ text: `effort ${step.effort}`, hot: false })
  return (
    <p
      className="mt-1 font-mono text-[12px] tabular-nums text-slate-400"
      data-testid="step-limits"
    >
      {parts.map((part, i) => (
        <span key={part.text}>
          {i > 0 ? ' · ' : ''}
          <span className={cn(part.hot && 'text-amber-300')}>{part.text}</span>
        </span>
      ))}
    </p>
  )
}

/** What the step waits for, and for a step not yet started whether it can start, is waiting, or is blocked. */
function DependencyLine({ step }: { step: WorkflowStepView }) {
  const depends = dependsText(step)
  const readiness = step.status === 'pending' ? step.readiness : null
  if (!depends && !readiness) return null
  return (
    <p
      className="mt-1 text-[12px] text-slate-400"
      data-testid="step-deps"
      data-readiness={readiness?.state ?? 'started'}
    >
      {depends}
      {readiness ? (
        <>
          {depends ? ' · ' : ''}
          <span
            className={cn(
              readiness.state === 'ready' && 'text-emerald-300',
              readiness.state === 'blocked' && 'text-amber-300',
            )}
          >
            {readiness.state === 'ready'
              ? 'Ready to start'
              : readiness.state === 'blocked'
                ? `Blocked: ${readiness.reason ?? 'a dependency will not complete'}`
                : `Not ready: ${readiness.reason ?? 'waiting on dependencies'}`}
          </span>
        </>
      ) : null}
    </p>
  )
}

/** Where the step works: its own worktree and branch, the commit it started from and how that start was merged. */
function WorkspaceLine({ step }: { step: WorkflowStepView }) {
  const ws = step.workspace
  if (!ws) return null
  const merge = mergeText(ws)
  return (
    <div
      className="mt-1 font-mono text-[12px] text-slate-400"
      data-testid="step-workspace"
      data-kind={ws.kind}
      data-merge={ws.merge_result ?? 'none'}
    >
      <p className="break-all">
        {ws.kind === 'lane' ? 'Lane' : 'Run worktree'} {ws.branch}
        {ws.retired
          ? ' (directory removed, branch kept)'
          : ` at ${ws.worktree}`}
      </p>
      <p>
        base {ws.base_sha ? ws.base_sha.slice(0, 8) : 'unknown'}
        {ws.start_sha ? ` · start ${ws.start_sha.slice(0, 8)}` : ''}
      </p>
      {merge ? (
        <p
          className={cn(
            ws.merge_result === 'conflict' || ws.merge_result === 'pending'
              ? 'text-amber-300'
              : 'text-slate-400',
          )}
        >
          {merge}
        </p>
      ) : null}
    </div>
  )
}

/** What the running attempt is doing. Display only: nothing here stops or restarts the step. */
function LiveLine({ step }: { step: WorkflowStepView }) {
  const live = liveStatus(step.live)
  return (
    <p
      className="mt-1 text-[12px] text-slate-300"
      data-testid="step-live"
      data-phase={live.phase ?? 'unknown'}
    >
      <span className="font-medium">{live.phaseText}</span>
      <span className="text-slate-400">
        {' · '}
        {live.activityText}
        {' · '}
      </span>
      <span
        className={cn(
          live.process === 'alive' ? 'text-emerald-300' : 'text-amber-300',
        )}
      >
        {live.processText}
      </span>
      {live.staleText ? (
        <span className="text-amber-300">
          {' · '}
          {live.staleText}
        </span>
      ) : null}
    </p>
  )
}

export function StepCard({
  step,
  limits,
  runId,
  runOpen = false,
}: {
  step: WorkflowStepView
  limits?: RunLimits
  /** With `runOpen`, the card offers to cancel the step. */
  runId?: string
  /** The run is still going (running or waiting for you). */
  runOpen?: boolean
}) {
  const decision = step.owner_decision
  const stoppable = ['pending', 'running', 'needs_owner'].includes(step.status)
  const cancelling =
    step.cancelling === true ||
    (step.status === 'running' && Boolean(step.cancel))
  return (
    <li
      id={`step-${step.key}`}
      data-testid="step"
      data-step-key={step.key}
      className="relative rounded-lg border border-slate-800 bg-slate-950/70 p-3"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-[11px] text-slate-500">
          {step.position + 1}
        </span>
        <h3 className="text-sm font-semibold text-slate-100">{step.key}</h3>
        <StatusDot
          status={step.status}
          label={STEP_STATUS_LABEL[step.status] ?? step.status}
        />
        <span className="text-[12px] text-slate-500">
          agent {step.agent_slug}
        </span>
        {cancelling ? (
          <span className="text-[12px] text-amber-300">Cancelling</span>
        ) : null}
        {step.heartbeat_at && step.status === 'running' ? (
          <span className="text-[12px] text-slate-500">
            last sign of life {formatRelativeTime(step.heartbeat_at)}
          </span>
        ) : null}
      </div>
      <DependencyLine step={step} />
      {step.status === 'running' ? <LiveLine step={step} /> : null}
      <WorkspaceLine step={step} />
      {step.chain && step.chain.length > 0 ? (
        <p className="mt-1 text-[12px] text-slate-500">
          Model chain: {step.chain.map(modelLabel).join(' then ')}
        </p>
      ) : null}
      {step.attempts > 0 ? <LimitLine step={step} limits={limits} /> : null}
      {step.cancel ? (
        <p role="note" className="mt-1 text-[12px] text-slate-300">
          {cancelText(step.cancel, 'step', step.status === 'cancelled')}
        </p>
      ) : null}
      {runId && runOpen && stoppable && !cancelling ? (
        <div className="mt-2">
          <CancelButton runId={runId} stepKey={step.key} />
        </div>
      ) : null}
      {decision ? (
        <p className="mt-1 text-[12px] text-slate-300">
          You chose to {decision.action}
          {decision.model ? ` on ${modelLabel(decision.model)}` : ''}.
        </p>
      ) : null}

      {step.attempt_history.length > 0 ? (
        <ol className="mt-3 space-y-2" aria-label={`Attempts for ${step.key}`}>
          {step.attempt_history.map((attempt) => (
            <AttemptCard key={attempt.session_id} attempt={attempt} />
          ))}
        </ol>
      ) : (
        <p className="mt-3 text-[12px] text-slate-500">
          {step.status === 'skipped'
            ? 'Skipped before any attempt.'
            : step.status === 'cancelled'
              ? 'Cancelled before any attempt.'
              : 'No attempts yet.'}
        </p>
      )}
      <HandoffNote step={step} />
    </li>
  )
}
