import { Tooltip } from '@/components/memory/Tooltip'
import type { LiveActivity } from '@/lib/api/sessions'
import { cn } from '@/lib/utils'
import { getSessionDisplayStatus } from '../utils'

export function StatusCell({
  status,
  liveActivity,
}: {
  status: string
  liveActivity?: LiveActivity | null
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
