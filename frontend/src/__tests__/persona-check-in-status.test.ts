import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  formatCheckInSummary,
  isCheckInScheduleOff,
  latestCheckIn,
} from '@/app/persona/utils/checkInStatus'

const base = {
  interval_minutes: 60,
  last_run: '2026-04-09T12:00:00Z',
  last_success: null,
  last_skip_reason: null,
}

describe('persona check-in status', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-09T12:00:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('states the schedule is off when the heartbeat skipped as disabled', () => {
    const status = { ...base, last_skip_reason: 'schedule_disabled' }
    expect(isCheckInScheduleOff(status)).toBe(true)
    expect(formatCheckInSummary(status)).toBe(
      'Scheduled check-ins off · last ran 6 months ago',
    )
  })

  it('treats a zero interval as the schedule being off', () => {
    expect(
      formatCheckInSummary({ ...base, interval_minutes: 0, last_run: null }),
    ).toBe('Scheduled check-ins off')
  })

  it('uses the newest of last_run and last_success', () => {
    const status = { ...base, last_success: '2026-10-09T11:00:00Z' }
    expect(latestCheckIn(status)).toBe('2026-10-09T11:00:00Z')
    expect(formatCheckInSummary(status)).toBe('Last check-in about 1 hour ago')
  })

  it('returns null when there is no check-in and the schedule is on', () => {
    expect(formatCheckInSummary({ ...base, last_run: null })).toBeNull()
    expect(formatCheckInSummary(null)).toBeNull()
  })
})
