import type { RequestErrors } from '@/lib/api/sessions'
import { cn } from '@/lib/utils'

export function requestErrorsText(errors: RequestErrors) {
  const noun = errors.count === 1 ? 'failed request' : 'failed requests'
  const category = errors.last_category.replaceAll('_', ' ')
  const message = errors.last_message ? ` – ${errors.last_message}` : ''
  return {
    short: `${errors.count} failed`,
    long: `${errors.count} ${noun}`,
    last: `Last: ${category}${message}`,
  }
}

/** Failed provider requests the harness still exited normally on. */
export function RequestErrorsBadge({
  errors,
  className,
}: {
  errors: RequestErrors | null | undefined
  className?: string
}) {
  if (!errors || errors.count <= 0) return null
  const text = requestErrorsText(errors)
  return (
    <span
      data-testid="request-errors"
      title={`${text.long}. ${text.last}`}
      aria-label={`${text.long}. ${text.last}`}
      className={cn(
        'shrink-0 rounded border border-rose-400/40 bg-rose-500/10 px-1.5 text-[11px] leading-5 text-rose-200',
        className,
      )}
    >
      {text.short}
    </span>
  )
}
