import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  HealthMetricsStrip,
  TimestampRow,
} from '@/components/settings/ProviderStatusParts'

describe('ProviderStatusParts', () => {
  it('shows Slow for latency-only degraded health', () => {
    render(
      <HealthMetricsStrip
        health={{
          state: 'degraded',
          latency_ms: 7000,
          error_rate: 0,
          availability: 1,
          consecutive_failures: 0,
          last_check: Date.now() / 1000,
          last_success: Date.now() / 1000,
          last_error: null,
        }}
      />,
    )

    expect(screen.getByText('Slow')).toBeInTheDocument()
    expect(screen.queryByText('Degraded')).not.toBeInTheDocument()
  })

  it('labels API-key timestamps as credentials updated', () => {
    render(
      <TimestampRow
        authSince="2026-03-05T16:53:01.101456Z"
        healthData={undefined}
      />,
    )

    expect(screen.getByText(/Credentials updated/)).toBeInTheDocument()
  })
})
