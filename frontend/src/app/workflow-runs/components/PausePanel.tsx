'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  type ResumeAction,
  resumeWorkflowRun,
  type WorkflowRunDetail,
} from '@/lib/api/workflow-runs'
import { modelLabel, pauseExplanation } from '../utils'

const button =
  'h-8 rounded-md border px-3 text-[12px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50 disabled:opacity-60'

/** A run waiting on the owner: why, and the retry, skip and end actions of the resume endpoint. */
export function PausePanel({ run }: { run: WorkflowRunDetail }) {
  const queryClient = useQueryClient()
  const pause = run.pause
  const stepKey = pause?.step_key
  const step = run.steps.find((s) => s.key === stepKey)
  const [model, setModel] = useState('')
  const [confirmEnd, setConfirmEnd] = useState(false)
  const [extra, setExtra] = useState('')

  const atCap =
    step !== undefined &&
    step.attempt_limit !== undefined &&
    step.attempts >= step.attempt_limit
  const extraAttempts = atCap ? Math.max(0, Math.floor(Number(extra) || 0)) : 0

  const resume = useMutation({
    mutationFn: (action: ResumeAction) =>
      resumeWorkflowRun(run.id, {
        action,
        step_key: stepKey,
        model: action === 'retry' && model ? model : undefined,
        ...(action === 'retry' && extraAttempts > 0
          ? { extra_attempts: extraAttempts }
          : {}),
      }),
    onSuccess: () => {
      setConfirmEnd(false)
      return queryClient.invalidateQueries({ queryKey: ['workflow-runs'] })
    },
  })

  if (run.state !== 'needs_owner' || !pause) return null
  const chain = step?.chain ?? []

  if (pause.reason === 'blocked_dependencies') {
    // Nothing to retry or skip: the plan itself has to change (the coordinator edits it through the API).
    const blocked = Object.entries(pause.blocked ?? {})
    return (
      <section
        aria-labelledby="pause-heading"
        className="mb-4 rounded-lg border border-amber-500/40 bg-amber-950/25 p-3"
      >
        <h2 id="pause-heading" className="text-sm font-semibold text-amber-100">
          Blocked on dependencies
        </h2>
        <p className="mt-1 text-[13px] text-amber-50/90">
          {pauseExplanation(pause, stepKey)}
        </p>
        <ul className="mt-2 list-disc pl-5 text-[12px] text-amber-50/80">
          {blocked.map(([key, readiness]) => (
            <li key={key}>
              {key}: {readiness.reason ?? 'blocked'}
            </li>
          ))}
        </ul>
      </section>
    )
  }

  return (
    <section
      aria-labelledby="pause-heading"
      className="mb-4 rounded-lg border border-amber-500/40 bg-amber-950/25 p-3"
    >
      <h2 id="pause-heading" className="text-sm font-semibold text-amber-100">
        Waiting for you
      </h2>
      <p className="mt-1 text-[13px] text-amber-50/90">
        {pauseExplanation(pause, stepKey)}
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-[11px] text-slate-400">
          Retry on
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={resume.isPending}
            className="h-8 rounded-md border border-slate-700 bg-slate-950 px-2 text-[12px] text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
          >
            <option value="">The agent&apos;s model chain</option>
            {chain.map((id) => (
              <option key={id} value={id}>
                {modelLabel(id)} ({id})
              </option>
            ))}
          </select>
        </label>
        {atCap ? (
          <label className="flex flex-col gap-1 text-[11px] text-slate-400">
            Add attempts (step is at {step?.attempts} of {step?.attempt_limit})
            <input
              type="number"
              min={1}
              inputMode="numeric"
              value={extra}
              onChange={(e) => setExtra(e.target.value)}
              disabled={resume.isPending}
              className="h-8 w-24 rounded-md border border-slate-700 bg-slate-950 px-2 text-[12px] text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
            />
          </label>
        ) : null}
        <button
          type="button"
          disabled={resume.isPending}
          onClick={() => resume.mutate('retry')}
          className={`${button} border-amber-400/50 bg-amber-500/15 text-amber-50 hover:bg-amber-500/25`}
        >
          Retry step
        </button>
        <button
          type="button"
          disabled={resume.isPending}
          onClick={() => resume.mutate('skip')}
          className={`${button} border-slate-700 bg-slate-900 text-slate-200 hover:bg-slate-800`}
        >
          Skip step
        </button>
        {confirmEnd ? (
          <>
            <button
              type="button"
              disabled={resume.isPending}
              onClick={() => resume.mutate('fail')}
              className={`${button} border-rose-400/60 bg-rose-500/20 text-rose-50 hover:bg-rose-500/30`}
            >
              Confirm: end run as failed
            </button>
            <button
              type="button"
              onClick={() => setConfirmEnd(false)}
              className={`${button} border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800`}
            >
              Keep run
            </button>
          </>
        ) : (
          <button
            type="button"
            disabled={resume.isPending}
            onClick={() => setConfirmEnd(true)}
            className={`${button} border-rose-500/40 bg-transparent text-rose-200 hover:bg-rose-950/40`}
          >
            End run
          </button>
        )}
      </div>
      {resume.isPending ? (
        <p role="status" className="mt-2 text-[12px] text-slate-400">
          Sending your decision
        </p>
      ) : null}
      {resume.isError ? (
        <p role="alert" className="mt-2 text-[12px] text-rose-300">
          {resume.error instanceof Error
            ? resume.error.message
            : 'Resume failed'}
          . Nothing changed; try again.
        </p>
      ) : null}
    </section>
  )
}
