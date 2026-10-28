import { formatRelativeTime } from '@/app/sessions/utils'
import type { WorkflowStepView } from '@/lib/api/workflow-runs'
import { modelLabel, STEP_STATUS_LABEL } from '../utils'
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

export function StepCard({ step }: { step: WorkflowStepView }) {
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
      {step.restarts > 0 ? (
        <p className="mt-1 text-[12px] text-amber-300">
          Restarted {step.restarts} {step.restarts === 1 ? 'time' : 'times'}{' '}
          after a stalled attempt
        </p>
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
            : 'No attempts yet.'}
        </p>
      )}
      <HandoffNote step={step} />
    </li>
  )
}
