import { formatDistanceToNow } from 'date-fns'
import type { HeartbeatStatusResponse } from '@/lib/api/dashboard'

type CheckInStatus = Pick<
  HeartbeatStatusResponse,
  'interval_minutes' | 'last_run' | 'last_success' | 'last_skip_reason'
>

/** Skip reasons the heartbeat records when scheduled check-ins are turned off. */
const SCHEDULE_OFF_SKIP_REASONS = new Set(['disabled', 'schedule_disabled'])

export function isCheckInScheduleOff(status: CheckInStatus): boolean {
  return (
    status.interval_minutes === 0 ||
    SCHEDULE_OFF_SKIP_REASONS.has(status.last_skip_reason ?? '')
  )
}

/** Most recent completed check-in, scheduled or manual. */
export function latestCheckIn(status: CheckInStatus): string | null {
  const times = [status.last_run, status.last_success].filter(
    (value): value is string =>
      typeof value === 'string' && !Number.isNaN(Date.parse(value)),
  )
  if (times.length === 0) return null
  return times.reduce((latest, value) =>
    Date.parse(value) > Date.parse(latest) ? value : latest,
  )
}

/**
 * One-line check-in state for the persona header. States the schedule is off
 * when it is, so an old last-run time is not read as a stalled schedule.
 */
export function formatCheckInSummary(
  status: CheckInStatus | null | undefined,
): string | null {
  if (!status) return null
  const latest = latestCheckIn(status)
  const ago = latest
    ? formatDistanceToNow(new Date(latest), { addSuffix: true })
    : null
  if (isCheckInScheduleOff(status)) {
    return ago
      ? `Scheduled check-ins off · last ran ${ago}`
      : 'Scheduled check-ins off'
  }
  return ago ? `Last check-in ${ago}` : null
}
