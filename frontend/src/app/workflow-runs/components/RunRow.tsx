import Link from 'next/link'
import {
  formatCost,
  formatRelativeTime,
  formatTokens,
} from '@/app/sessions/utils'
import type { WorkflowRunListItem } from '@/lib/api/workflow-runs'
import { modelLabel, runStateLabel } from '../utils'
import { StatusDot } from './StatusDot'

const GRID =
  'lg:grid lg:grid-cols-[110px_minmax(12rem,1fr)_96px_minmax(10rem,16rem)_84px_120px_90px_80px] lg:items-center'

export function RunRowHeader() {
  const cell = 'text-[11px] font-medium uppercase tracking-wide text-slate-500'
  return (
    <div className={`hidden gap-3 border-b border-slate-800 px-3 py-2 ${GRID}`}>
      <span className={cell}>State</span>
      <span className={cell}>Goal</span>
      <span className={cell}>Steps</span>
      <span className={cell}>Models</span>
      <span className={`${cell} text-right`}>Attempts</span>
      <span className={`${cell} text-right`}>Tokens / cost</span>
      <span className={`${cell} text-right`}>Started</span>
      <span className={`${cell} text-right`}>Updated</span>
    </div>
  )
}

function stepsText(run: WorkflowRunListItem): string {
  const done = (run.step_counts.completed ?? 0) + (run.step_counts.skipped ?? 0)
  return `${done} of ${run.step_total} done`
}

function usageText(run: WorkflowRunListItem): { tokens: string; cost: string } {
  return {
    tokens:
      run.total_tokens === null
        ? 'tokens n/a'
        : `${formatTokens(run.total_tokens)} tok`,
    cost: run.cost_usd === null ? 'cost n/a' : formatCost(run.cost_usd),
  }
}

export function RunRow({ run }: { run: WorkflowRunListItem }) {
  const usage = usageText(run)
  const models = run.served_models.map(modelLabel)
  const lastActive = run.last_activity_at ?? run.created_at
  return (
    <li className="border-b border-slate-800/50 last:border-b-0">
      <Link
        href={`/workflow-runs/${encodeURIComponent(run.id)}`}
        data-testid="workflow-run-row"
        className={`flex flex-col gap-1 px-3 py-2.5 text-[13px] outline-none hover:bg-slate-900/40 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber-400/60 lg:gap-3 ${GRID}`}
      >
        <div className="flex flex-col gap-0.5">
          <StatusDot status={run.state} label={runStateLabel(run.state)} />
          {run.state === 'needs_owner' && run.pause_reason ? (
            <span className="truncate text-[11px] text-slate-500">
              {run.pause_reason.replaceAll('_', ' ')}
            </span>
          ) : null}
        </div>
        <div className="min-w-0">
          <p className="truncate text-slate-100" title={run.goal ?? undefined}>
            {run.goal ?? 'No goal recorded'}
          </p>
          <p className="truncate font-mono text-[11px] text-slate-500">
            {run.project_id ?? 'no project'} · {run.id.slice(0, 8)}
          </p>
        </div>
        <span className="font-mono text-[12px] text-slate-300">
          {stepsText(run)}
        </span>
        <span
          className="min-w-0 truncate text-slate-300"
          title={run.served_models.join(', ')}
        >
          {models.length > 0 ? (
            models.join(', ')
          ) : (
            <span className="text-slate-500">no attempts yet</span>
          )}
        </span>
        <span className="flex items-baseline gap-2 font-mono text-[12px] tabular-nums text-slate-300 lg:flex-col lg:items-end lg:gap-0">
          <span>
            {run.attempt_count}{' '}
            {run.attempt_count === 1 ? 'attempt' : 'attempts'}
          </span>
          {run.flagged_attempts > 0 ? (
            <span
              className="text-amber-300"
              title="Attempts that were refused, substituted, hit a usage limit or were interrupted"
            >
              {run.flagged_attempts} flagged
            </span>
          ) : null}
        </span>
        <span className="flex items-baseline gap-2 font-mono text-[12px] tabular-nums text-slate-300 lg:flex-col lg:items-end lg:gap-0">
          <span>{usage.tokens}</span>
          <span>{usage.cost}</span>
        </span>
        <span
          className="text-[12px] text-slate-400 lg:text-right"
          title={
            run.created_at
              ? new Date(run.created_at).toLocaleString()
              : undefined
          }
        >
          <span className="lg:hidden">started </span>
          {formatRelativeTime(run.created_at)}
        </span>
        <span className="text-[12px] text-slate-400 lg:text-right">
          <span className="lg:hidden">updated </span>
          {formatRelativeTime(lastActive)}
        </span>
      </Link>
    </li>
  )
}
