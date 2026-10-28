import { ArrowRight } from 'lucide-react'
import Link from 'next/link'
import { formatDurationMs, formatTokens } from '@/app/sessions/utils'
import type { AcceptanceResult, WorkflowAttempt } from '@/lib/api/workflow-runs'
import { cn } from '@/lib/utils'
import {
  attemptCostText,
  attemptDurationMs,
  attemptModels,
  attemptTokens,
  categoryText,
  executorLabel,
  formatResetTime,
  modelLabel,
} from '../utils'

function Model({ id }: { id: string | null }) {
  return (
    <span className="font-medium text-slate-100" title={id ?? undefined}>
      {modelLabel(id)}
    </span>
  )
}

/** What the model did with the request, when it did not simply answer. */
function OutcomeNotice({ attempt }: { attempt: WorkflowAttempt }) {
  const outcome = attempt.outcome
  const base = 'rounded-md border px-2.5 py-1.5 text-[12px]'
  if (outcome?.kind === 'refused') {
    return (
      <div
        role="note"
        className={cn(base, 'border-rose-500/40 bg-rose-950/30 text-rose-100')}
      >
        <strong>Refused{categoryText(outcome.category)}.</strong>{' '}
        {outcome.explanation ?? 'The model declined this request.'}
      </div>
    )
  }
  if (outcome?.kind === 'usage_limit') {
    const reset = formatResetTime(outcome.resets_at)
    return (
      <div
        role="note"
        className={cn(base, 'border-sky-500/40 bg-sky-950/30 text-sky-100')}
      >
        <strong>
          Usage limit reached
          {outcome.window ? ` (${outcome.window.replaceAll('_', ' ')})` : ''}.
        </strong>{' '}
        {reset ? `Resets ${reset}.` : 'No reset time was reported.'}
      </div>
    )
  }
  if (outcome?.kind === 'interrupted') {
    return (
      <div
        role="note"
        className={cn(
          base,
          'border-amber-500/40 bg-amber-950/30 text-amber-100',
        )}
      >
        <strong>Interrupted.</strong>{' '}
        {outcome.explanation ?? 'The stream ended before the model finished.'}
      </div>
    )
  }
  if (attempt.error && attempt.status !== 'completed') {
    return (
      <div
        role="note"
        className={cn(base, 'border-rose-500/40 bg-rose-950/30 text-rose-100')}
      >
        <strong>Error.</strong>{' '}
        <span className="break-words">{attempt.error}</span>
      </div>
    )
  }
  return null
}

/** The runner's own check of the step after the agent said it was done. */
function AcceptanceChecks({ results }: { results: AcceptanceResult[] }) {
  return (
    <div data-testid="acceptance" className="mt-2 text-[12px]">
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
        Acceptance checks
      </p>
      <ul className="mt-1 space-y-1">
        {results.map((result) => (
          <li key={result.cmd}>
            <details open={!result.passed && result.output_tail.length > 0}>
              <summary className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50">
                <span
                  className={cn(
                    'font-medium',
                    result.passed ? 'text-emerald-300' : 'text-rose-300',
                  )}
                >
                  {result.passed
                    ? 'Passed'
                    : result.timed_out
                      ? 'Timed out'
                      : `Failed (exit ${result.exit_code ?? 'n/a'})`}
                </span>{' '}
                <code className="break-all font-mono text-slate-300">
                  {result.cmd}
                </code>{' '}
                <span className="font-mono tabular-nums text-slate-500">
                  {result.duration_s}s
                </span>
              </summary>
              {result.output_tail ? (
                <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md border border-slate-800 bg-slate-900/60 p-2 font-mono text-[11px] text-slate-300">
                  {result.output_tail}
                </pre>
              ) : (
                <p className="mt-1 text-slate-500">No output.</p>
              )}
            </details>
          </li>
        ))}
      </ul>
    </div>
  )
}

const FAILED_LABEL: Record<string, string> = {
  refused: 'Refused',
  usage_limit: 'Usage limit',
  interrupted: 'Interrupted',
}

function failedLabel(attempt: WorkflowAttempt): string {
  return FAILED_LABEL[attempt.outcome?.kind ?? ''] ?? 'Failed'
}

export function AttemptCard({ attempt }: { attempt: WorkflowAttempt }) {
  const models = attemptModels(attempt)
  const finished = Boolean(attempt.finished_at)
  const running = !finished && attempt.status === 'active'
  const duration = attemptDurationMs(attempt)
  const tokens = attemptTokens(attempt)
  const cost = attemptCostText(attempt)
  const hop = attempt.hop_from
  const next = attempt.next_hop
  const statusText = running
    ? 'Running'
    : attempt.status === 'completed'
      ? 'Done'
      : failedLabel(attempt)

  return (
    <li
      data-testid="attempt"
      data-substituted={models.substituted ? 'true' : undefined}
      className="rounded-md border border-slate-800 bg-slate-950/50 p-3"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[13px] font-semibold text-slate-100">
          Attempt {attempt.attempt}
        </span>
        <span className="text-[12px] text-slate-400">
          {executorLabel(attempt.executor)}
        </span>
        <span className="text-[12px] text-slate-400">{statusText}</span>
        <span className="ml-auto font-mono text-[11px] tabular-nums text-slate-400">
          {duration !== null
            ? formatDurationMs(duration)
            : finished
              ? 'duration n/a'
              : 'running'}
          {' · '}
          {typeof tokens === 'number'
            ? `${formatTokens(tokens)} tok`
            : 'tokens n/a'}
          {' · '}
          {cost}
        </span>
      </div>

      <div className="mt-2 text-[13px] text-slate-300">
        {models.substituted ? (
          <div
            role="note"
            className="rounded-md border border-amber-500/50 bg-amber-950/30 px-2.5 py-1.5 text-amber-100"
          >
            <p>
              <strong>Substituted:</strong> asked <Model id={models.asked} />,
              answered by <Model id={models.answered} />
            </p>
            {attempt.outcome?.kind === 'substituted' ? (
              <p className="mt-0.5 text-[12px] text-amber-200/80">
                The provider switched models
                {categoryText(attempt.outcome.category)}.
                {attempt.outcome.explanation
                  ? ` ${attempt.outcome.explanation}`
                  : ''}
              </p>
            ) : null}
          </div>
        ) : models.answered ? (
          <p>
            Asked and answered by <Model id={models.asked} />
          </p>
        ) : (
          <p>
            Asked <Model id={models.asked} />
            {running ? ', answer pending' : ''}
          </p>
        )}
      </div>

      {hop ? (
        <p className="mt-1.5 text-[12px] text-slate-400">
          Took over from{' '}
          <span className="text-slate-300">{modelLabel(hop.from_model)}</span>{' '}
          after {hop.kind.replaceAll('_', ' ')}
          {categoryText(hop.category)}.
        </p>
      ) : null}

      <div className="mt-2 space-y-1.5">
        <OutcomeNotice attempt={attempt} />
        {next ? (
          <p className="flex flex-wrap items-center gap-1 text-[12px] text-slate-400">
            <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            Moved on to{' '}
            <span className="text-slate-300">{modelLabel(next.to_model)}</span>
          </p>
        ) : null}
      </div>

      {attempt.acceptance && attempt.acceptance.length > 0 ? (
        <AcceptanceChecks results={attempt.acceptance} />
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px]">
        <Link
          href={`/sessions?sel=${encodeURIComponent(attempt.session_id)}`}
          className="text-amber-300 underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
        >
          Open attempt session
        </Link>
        {attempt.transcript_path ? (
          <span className="min-w-0 break-all font-mono text-[11px] text-slate-500">
            transcript {attempt.transcript_path}
          </span>
        ) : (
          <span className="text-slate-500">No transcript file recorded</span>
        )}
      </div>
    </li>
  )
}
