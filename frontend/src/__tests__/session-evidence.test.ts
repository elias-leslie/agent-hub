import { describe, expect, it } from 'vitest'

import {
  liveWarnings,
  terminationText,
} from '@/app/sessions/components/SessionEvidence'
import type { Session } from '@/lib/api/sessions'

describe('terminationText', () => {
  it('says how a session ended in plain words instead of the backend code', () => {
    expect(terminationText('session_closed_helper')).toBe(
      'Closed when its work finished',
    )
    expect(terminationText('session_reaper_global_timeout')).toBe(
      'Closed after going idle',
    )
  })

  it('turns unknown codes into words and keeps error messages as written', () => {
    expect(terminationText('cleanup_closed:abandoned')).toBe(
      'Ended: cleanup closed, abandoned',
    )
    expect(terminationText('heartbeat_dead+no_lane')).toBe(
      'Ended: heartbeat dead no lane',
    )
    expect(terminationText('TimeoutError: provider stream went silent')).toBe(
      'Ended: TimeoutError: provider stream went silent',
    )
  })

  it('warns about abnormal endings only', () => {
    const ended = (reason: string) =>
      ({ live_activity: { termination_reason: reason } }) as unknown as Session
    expect(liveWarnings(ended('session_closed_helper'))).toEqual([])
    expect(liveWarnings(ended('session_reaper_global_timeout'))).toEqual([
      'Closed after going idle',
    ])
  })
})
