'use client'

import Link from 'next/link'
import { useWorkflowRun } from '@/app/workflow-runs/hooks/useWorkflowRuns'
import { executorLabel } from '@/app/workflow-runs/utils'
import type { Session, SessionListItem } from '@/lib/api/sessions'
import { getExecutionIdentity } from '../utils'
import { ModelPill } from './ModelPill'

/** The workflow run a session belongs to: attempts are children of their run, started by the workflow runner. */
export function workflowRunIdOf(
  source: Pick<Session, 'request_source' | 'parent_session_id'>,
): string | null {
  return source.request_source === 'workflow_run' && source.parent_session_id
    ? source.parent_session_id
    : null
}

/**
 * Which workflow run and step an attempt's session belongs to, with a link back to the run page.
 * The run is read from the run API; while it loads or when it cannot be read the link to the run still shows.
 */
export function WorkflowOrigin({
  source,
}: {
  source: Session | SessionListItem
}) {
  const runId = workflowRunIdOf(source)
  const { run, isLoading, error } = useWorkflowRun(runId ?? '')
  if (!runId) return null
  const step = run?.steps.find((candidate) =>
    candidate.attempt_history.some((a) => a.session_id === source.id),
  )
  const attempt = step?.attempt_history.find((a) => a.session_id === source.id)
  const identity = getExecutionIdentity(source)
  const href = `/workflow-runs/${encodeURIComponent(runId)}${step ? `#step-${encodeURIComponent(step.key)}` : ''}`
  return (
    <div
      data-testid="workflow-origin"
      className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px]"
    >
      <span className="text-slate-500">workflow</span>
      <Link
        href={href}
        className="text-sky-700 dark:text-sky-300 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
        title={run?.goal ?? runId}
      >
        run {runId.slice(0, 8)}
        {step ? ` · step ${step.key}` : ''}
        {attempt ? ` · attempt ${attempt.attempt}` : ''} ↗
      </Link>
      <ModelPill
        model={identity.effectiveModel}
        provider={identity.effectiveProvider}
        fallbackUsed={identity.fallbackUsed}
      />
      {attempt?.executor ? (
        <span className="text-slate-400">
          {executorLabel(attempt.executor)}
        </span>
      ) : null}
      {isLoading ? (
        <span className="italic text-slate-500">loading run…</span>
      ) : error ? (
        <span className="italic text-slate-500">run details unavailable</span>
      ) : run && !step ? (
        <span className="italic text-slate-500">not listed in the run</span>
      ) : null}
    </div>
  )
}
