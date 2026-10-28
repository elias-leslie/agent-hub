import { formatRelativeTime } from '@/app/sessions/utils'
import type { RunLimits, WorkflowStepView } from '@/lib/api/workflow-runs'
import { cn } from '@/lib/utils'
import { atLimit, modelLabel, ofLimit, STEP_STATUS_LABEL } from '../utils'
import { AttemptCard } from './AttemptCard'
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
    parts.push({
      text: `usage-limit resumes ${ofLimit(resumes, limits?.max_usage_limit_resumes)}`,
      hot: atLimit(resumes, limits?.max_usage_limit_resumes),
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

export function StepCard({
  step,
  limits,
}: {
  step: WorkflowStepView
  limits?: RunLimits
}) {
  const decision = step.owner_decision
  return (
    <li
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
        {step.heartbeat_at && step.status === 'running' ? (
          <span className="text-[12px] text-slate-500">
            last sign of life {formatRelativeTime(step.heartbeat_at)}
          </span>
        ) : null}
      </div>
      {step.chain && step.chain.length > 0 ? (
        <p className="mt-1 text-[12px] text-slate-500">
          Model chain: {step.chain.map(modelLabel).join(' then ')}
        </p>
      ) : null}
      {step.attempts > 0 ? <LimitLine step={step} limits={limits} /> : null}
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
            : 'No attempts yet.'}
        </p>
      )}
      <HandoffNote step={step} />
    </li>
  )
}
