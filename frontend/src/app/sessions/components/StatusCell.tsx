import { Tooltip } from '@/components/memory/Tooltip'
import type { LiveActivity } from '@/lib/api/sessions'
import { cn } from '@/lib/utils'
import { getSessionDisplayStatus } from '../utils'

export function StatusCell({
  status,
  liveActivity,
  showLabel = false,
}: {
  status: string
  liveActivity?: LiveActivity | null
  /** Render the state as text next to the dot so colour is never the only cue. */
  showLabel?: boolean
}) {
  const state = getSessionDisplayStatus({
    status,
    live_activity: liveActivity,
  })
  const mismatch =
    liveActivity &&
    (status === 'completed' || status === 'failed' || status === 'error') &&
    liveActivity.lifecycle_state === 'working'
  const label = mismatch ? `${state.label}, runtime mismatch` : state.label
  const dot = (
    <span
      className={cn(
        'h-2 w-2 shrink-0 rounded-full',
        mismatch ? 'bg-amber-300' : state.dotClassName,
      )}
    />
  )

  if (showLabel) {
    return (
      <span
        title={mismatch ? label : state.tooltip || label}
        className="inline-flex min-w-0 items-center gap-1.5 text-[12px] text-slate-300"
      >
        {dot}
        <span className="truncate">{mismatch ? 'mismatch' : state.label}</span>
      </span>
    )
  }

  return (
    <Tooltip content={label} position="top">
      <span
        aria-label={label}
        title={label}
        className={cn(
          'inline-flex h-6 w-6 cursor-help items-center justify-center rounded-full border',
          mismatch
            ? 'border-amber-300/60 bg-amber-400/10'
            : state.badgeClassName,
        )}
      >
        <span
          className={cn(
            'h-2.5 w-2.5 rounded-full',
            mismatch ? 'bg-amber-300' : state.dotClassName,
          )}
        />
      </span>
    </Tooltip>
  )
}
