'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { cancelWorkflowRun, cancelWorkflowStep } from '@/lib/api/workflow-runs'

const button =
  'h-8 rounded-md border px-3 text-[12px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50 disabled:opacity-60'

/**
 * Stops a run or one step. The first click only asks; the second, with an optional reason, sends it.
 * A running step is stopped by its worker within a few seconds, so the page keeps polling afterwards.
 */
export function CancelButton({
  runId,
  stepKey,
}: {
  runId: string
  /** Cancels this step only; without it the whole run. */
  stepKey?: string
}) {
  const queryClient = useQueryClient()
  const reasonId = useId()
  const [asking, setAsking] = useState(false)
  const [reason, setReason] = useState('')
  const what = stepKey ? 'step' : 'run'

  const cancel = useMutation({
    mutationFn: () =>
      stepKey
        ? cancelWorkflowStep(runId, stepKey, reason.trim() || undefined)
        : cancelWorkflowRun(runId, reason.trim() || undefined),
    onSuccess: () => {
      setAsking(false)
      setReason('')
      return queryClient.invalidateQueries({ queryKey: ['workflow-runs'] })
    },
  })

  return (
    <div
      className="flex flex-wrap items-end gap-2"
      data-testid={`cancel-${what}`}
    >
      {asking ? (
        <>
          <label
            htmlFor={reasonId}
            className="flex flex-col gap-1 text-[11px] text-slate-400"
          >
            Reason (optional)
            <input
              id={reasonId}
              value={reason}
              maxLength={2000}
              onChange={(e) => setReason(e.target.value)}
              disabled={cancel.isPending}
              className="h-8 w-56 rounded-md border border-slate-700 bg-slate-950 px-2 text-[12px] text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
            />
          </label>
          <button
            type="button"
            disabled={cancel.isPending}
            onClick={() => cancel.mutate()}
            className={`${button} border-rose-400/60 bg-rose-500/20 text-rose-50 hover:bg-rose-500/30`}
          >
            {`Confirm: cancel ${what}`}
          </button>
          <button
            type="button"
            disabled={cancel.isPending}
            onClick={() => {
              setAsking(false)
              cancel.reset()
            }}
            className={`${button} border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800`}
          >
            {`Keep ${what} going`}
          </button>
        </>
      ) : (
        <button
          type="button"
          onClick={() => setAsking(true)}
          className={`${button} border-rose-500/40 bg-transparent text-rose-200 hover:bg-rose-950/40`}
        >
          {`Cancel ${what}`}
        </button>
      )}
      {cancel.isPending ? (
        <span role="status" className="text-[12px] text-slate-400">
          Sending the cancel request
        </span>
      ) : null}
      {cancel.isError ? (
        <span role="alert" className="text-[12px] text-rose-300">
          {cancel.error instanceof Error
            ? cancel.error.message
            : 'Cancel failed'}
          . Nothing changed.
        </span>
      ) : null}
    </div>
  )
}
