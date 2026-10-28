'use client'

import { ArrowLeft, RefreshCw } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { formatDurationMs, formatTokens } from '@/app/sessions/utils'
import type { WorkflowRunDetail } from '@/lib/api/workflow-runs'
import { cn } from '@/lib/utils'
import { CancelButton } from '../components/CancelButton'
import { ErrorAlert, LoadingState } from '../components/ListStates'
import { PausePanel } from '../components/PausePanel'
import { PlanHistory } from '../components/PlanHistory'
import { StatusDot } from '../components/StatusDot'
import { StepCard } from '../components/StepCard'
import { useWorkflowRun } from '../hooks/useWorkflowRuns'
import {
  cancelText,
  costTotalsParts,
  resultText,
  runStateLabel,
} from '../utils'

function clock(ms: number): string {
  return ms ? new Date(ms).toLocaleTimeString() : ''
}

function RunSummary({ run }: { run: WorkflowRunDetail }) {
  const attempts = run.steps.flatMap((s) => s.attempt_history).length
  const tokens = run.usage_totals?.total_tokens ?? null
  const cost = run.usage_totals ? costTotalsParts(run.usage_totals.cost) : null
  const finished =
    run.state === 'completed' ||
    run.state === 'failed' ||
    run.state === 'cancelled'
  const open = run.state === 'running' || run.state === 'needs_owner'
  const cancelling =
    run.cancelling === true || (run.state === 'running' && Boolean(run.cancel))
  const elapsed =
    finished && run.created_at && run.last_activity_at
      ? formatDurationMs(
          new Date(run.last_activity_at).getTime() -
            new Date(run.created_at).getTime(),
        )
      : null
  const refusals = Object.entries(run.refusals ?? {})
  const running = run.running_steps ?? []
  return (
    <div className="mb-4 space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <StatusDot status={run.state} label={runStateLabel(run.state)} />
        {cancelling ? (
          <span className="text-[12px] text-amber-300">Cancelling</span>
        ) : null}
        <span className="font-mono text-[12px] text-slate-500">
          {run.project_id ?? 'no project'}
        </span>
        <span className="font-mono text-[12px] text-slate-500">{run.id}</span>
      </div>
      <p
        className="font-mono text-[12px] text-slate-500"
        data-testid="run-origin"
      >
        {run.launched_by
          ? `Launched by ${run.launched_by}${run.coordinator ? ` (${run.coordinator})` : ''}`
          : run.coordinator
            ? `Coordinator ${run.coordinator}`
            : 'Launcher not recorded'}
        {' · '}plan revision {run.plan_revision ?? 0}
      </p>
      <p className="whitespace-pre-wrap break-words text-sm text-slate-100">
        {run.goal ?? 'No goal recorded'}
      </p>
      <p className="font-mono text-[12px] tabular-nums text-slate-400">
        {attempts} {attempts === 1 ? 'attempt' : 'attempts'} ·{' '}
        {tokens === null ? 'tokens n/a' : `${formatTokens(tokens)} tok`} ·{' '}
        <span data-testid="run-cost">
          {cost ? cost.join(' · ') : 'cost n/a'}
        </span>
        {elapsed ? ` · ${elapsed}` : ''}
        {run.created_at
          ? ` · started ${new Date(run.created_at).toLocaleString()}`
          : ''}
      </p>
      {run.max_concurrent_steps !== undefined ? (
        <p
          className="font-mono text-[12px] tabular-nums text-slate-400"
          data-testid="run-concurrency"
        >
          {running.length} of {run.max_concurrent_steps} step
          {run.max_concurrent_steps === 1 ? '' : 's'} running
          {running.length > 0 ? `: ${running.join(', ')}` : ''}
          {run.uses_lanes ? ' · each step has its own worktree and branch' : ''}
        </p>
      ) : null}
      {resultText(run.result) ? (
        <p
          className={cn(
            'break-all font-mono text-[12px]',
            run.result?.state === 'conflict'
              ? 'text-amber-300'
              : 'text-slate-300',
          )}
          data-testid="run-result"
        >
          {resultText(run.result)}
          {run.result?.worktree ? ` · ${run.result.worktree}` : ''}
        </p>
      ) : null}
      {run.limits ? (
        <p
          className="font-mono text-[12px] tabular-nums text-slate-500"
          data-testid="run-limits"
        >
          Limits per step: {run.limits.max_total_attempts} attempts ·{' '}
          {run.limits.max_unproductive_usage_limit_resumes} idle usage-limit
          resumes · {run.limits.acceptance_retry_limit} acceptance retries ·{' '}
          {run.limits.restart_limit} restarts
          {' · '}
          {run.limits.refusal_pause_threshold} refusals per category in the run
        </p>
      ) : null}
      {refusals.length > 0 ? (
        <p className="text-[12px] text-amber-300">
          Refusals so far:{' '}
          {refusals
            .map(([category, count]) => `${category} x${count}`)
            .join(', ')}
        </p>
      ) : null}
      {run.cancel ? (
        <p
          role="note"
          className="rounded-md border border-slate-600 bg-slate-900/60 px-2.5 py-1.5 text-[13px] text-slate-200"
        >
          {cancelText(run.cancel, 'run', run.state === 'cancelled')}
          {run.state === 'cancelled'
            ? ' Steps that had not started were skipped.'
            : ' A running step is being stopped.'}
        </p>
      ) : null}
      {open && !cancelling ? <CancelButton runId={run.id} /> : null}
      {run.state === 'failed' && run.failure ? (
        <p
          role="note"
          className="rounded-md border border-rose-500/40 bg-rose-950/30 px-2.5 py-1.5 text-[13px] text-rose-100"
        >
          <strong>Run failed.</strong> {run.failure}
        </p>
      ) : null}
    </div>
  )
}

export default function WorkflowRunPage() {
  const params = useParams<{ id: string }>()
  const id = Array.isArray(params.id) ? params.id[0] : params.id
  const data = useWorkflowRun(id)
  const run = data.run
  const live = run?.state === 'running'

  return (
    <div className="page-shell bg-slate-950 text-slate-100">
      <div className="page-backdrop bg-slate-950/90" />
      <header className="page-header bg-slate-950/92">
        <div className="page-container flex flex-wrap items-center gap-2 px-4 py-3 lg:px-8">
          <Link
            href="/workflow-runs"
            className="inline-flex items-center gap-1 text-[12px] text-slate-400 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
            Workflow runs
          </Link>
          <h1 className="text-base font-semibold tracking-tight text-slate-100">
            Run
          </h1>
          <div className="ml-auto flex items-center gap-2 text-[12px] text-slate-500">
            {live ? <span>Live, refreshing every few seconds</span> : null}
            {data.updatedAt ? (
              <span>Updated {clock(data.updatedAt)}</span>
            ) : null}
            <button
              type="button"
              onClick={() => void data.refetch()}
              aria-label="Refresh run"
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-slate-800 bg-slate-950/60 px-2 text-slate-300 hover:border-slate-700 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
            >
              <RefreshCw
                className={
                  data.isFetching ? 'h-3.5 w-3.5 animate-spin' : 'h-3.5 w-3.5'
                }
              />
              Refresh
            </button>
          </div>
        </div>
      </header>

      <main className="relative px-4 lg:px-8">
        <div className="page-container min-w-0 py-4">
          {data.error ? (
            <ErrorAlert
              title={
                run ? 'Could not refresh this run' : 'Could not load this run'
              }
              error={data.error}
              onRetry={() => void data.refetch()}
              stale={
                run
                  ? `Showing the run as of ${clock(data.updatedAt)}; it may be out of date.`
                  : null
              }
            />
          ) : null}
          {data.isLoading ? <LoadingState label="Loading run" /> : null}
          {run ? (
            <>
              <RunSummary run={run} />
              <PausePanel run={run} />
              <PlanHistory history={run.plan_history ?? []} />
              <h2 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-slate-500">
                Steps
              </h2>
              <ol
                className="space-y-3"
                aria-label="Steps"
                data-testid="step-list"
              >
                {run.steps.map((step) => (
                  <StepCard
                    key={step.key}
                    step={step}
                    limits={run.limits}
                    runId={run.id}
                    runOpen={
                      (run.state === 'running' ||
                        run.state === 'needs_owner') &&
                      !run.cancel
                    }
                  />
                ))}
              </ol>
            </>
          ) : null}
        </div>
      </main>
    </div>
  )
}
