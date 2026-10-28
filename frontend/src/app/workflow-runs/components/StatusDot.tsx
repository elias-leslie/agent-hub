import { cn } from '@/lib/utils'
import { STATE_TONE } from '../utils'

/** State as dot plus text, so colour is never the only cue. */
export function StatusDot({
  status,
  label,
}: {
  status: string | null
  label: string
}) {
  const tone = STATE_TONE[status ?? 'pending'] ?? STATE_TONE.pending
  return (
    <span
      className={cn(
        'inline-flex min-w-0 items-center gap-1.5 text-[12px]',
        tone.text,
      )}
    >
      <span
        aria-hidden="true"
        className={cn('h-2 w-2 shrink-0 rounded-full', tone.dot)}
      />
      <span className="truncate">{label}</span>
    </span>
  )
}
