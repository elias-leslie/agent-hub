import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { KPISection } from '@/app/dashboard/components/KPISection'
import { ProviderStatusCard } from '@/components/dashboard/ProviderStatusCard'
import { HealthTabContent } from '@/components/dashboard/tabs/HealthTabContent'
import type { DashboardStatsResponse } from '@/lib/api/dashboard'

vi.mock('@/lib/api/dashboard', () => ({
  fetchProviderHealth: vi.fn(() =>
    Promise.resolve({
      providers: [
        {
          provider: 'codex',
          state: 'degraded',
          latency_ms: 812,
          availability: 0.8,
          consecutive_failures: 1,
          recent_calls: 10,
          recent_failures: 2,
          last_error: 'HTTP 502 from codex/gpt-5.5',
        },
      ],
    }),
  ),
}))

function stats(
  overrides: Partial<DashboardStatsResponse['requests']> = {},
): DashboardStatsResponse {
  return {
    period_days: 7,
    period_start: '2026-10-03T00:00:00Z',
    period_end: '2026-10-10T00:00:00Z',
    requests: {
      total_requests: 5,
      avg_latency_ms: 900,
      p50_latency_ms: 800,
      p95_latency_ms: 2000,
      success_rate: 0,
      error_count: 5,
      ...overrides,
    },
    requests_by_day: [],
    memory: {
      total_injections: 523,
      avg_latency_ms: 60,
      avg_tokens: 1722.9,
      total_mandates: 0,
      total_guardrails: 0,
      total_references: 4,
      total_reference_index_entries: 9,
      total_reference_citations: 1,
    },
    by_model: [],
    active_sessions: 1,
    total_sessions: 2505,
    total_cost_usd: 0,
    total_tokens: 0,
  }
}

describe('KPISection truthfulness', () => {
  it('shows a 0% success rate as 0%, not 100%', () => {
    render(
      <KPISection
        dashboardStats={stats()}
        activeSessionCount={0}
        totalCosts={undefined}
      />,
    )
    expect(screen.getByText('0.0%')).toBeInTheDocument()
    expect(screen.getByText('0.0% succeeded')).toBeInTheDocument()
    expect(screen.queryByText('100%')).not.toBeInTheDocument()
  })

  it('shows no rate when there were no model calls', () => {
    render(
      <KPISection
        dashboardStats={stats({
          total_requests: 0,
          success_rate: null,
          p50_latency_ms: null,
          p95_latency_ms: null,
          avg_latency_ms: null,
          error_count: 0,
        })}
        activeSessionCount={0}
        totalCosts={undefined}
      />,
    )
    expect(
      screen.getByText('No model calls in this period'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
    expect(screen.queryByText('100%')).not.toBeInTheDocument()
  })

  it('labels cost as metered spend and keeps selected vs passive refs', () => {
    render(
      <KPISection
        dashboardStats={stats()}
        activeSessionCount={0}
        totalCosts={undefined}
      />,
    )
    expect(screen.getByText('Metered spend')).toBeInTheDocument()
    expect(screen.getByText(/API-billed calls/)).toBeInTheDocument()
    expect(screen.getByText('4 selected, 9 passive refs')).toBeInTheDocument()
    expect(screen.queryByText('Timeouts')).not.toBeInTheDocument()
    expect(screen.queryByText('Fallbacks')).not.toBeInTheDocument()
  })
})

describe('HealthTabContent truthfulness', () => {
  it('drops HTTP success, truncation and circuit-breaker panels', async () => {
    render(<HealthTabContent stats={stats()} />)
    expect(screen.queryByText('Success Rate')).not.toBeInTheDocument()
    expect(screen.queryByText('Truncations')).not.toBeInTheDocument()
    expect(screen.queryByText('Circuit Breakers')).not.toBeInTheDocument()
    expect(screen.getByText('Selected refs')).toBeInTheDocument()
    expect(screen.getByText('Passive index refs')).toBeInTheDocument()
    expect(screen.getByText('9')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText('Calls 24h')).toBeInTheDocument()
    })
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
  })
})

describe('ProviderStatusCard recent failures', () => {
  it('shows the failing outcome from recent completions', () => {
    render(
      <ProviderStatusCard
        provider={{
          name: 'codex',
          available: true,
          configured: true,
          error: null,
          health: {
            state: 'degraded',
            latency_ms: 500,
            error_rate: 0.2,
            availability: 0.8,
            consecutive_failures: 1,
            last_check: null,
            last_success: null,
            last_error: 'HTTP 502 from codex/gpt-5.5',
          },
        }}
      />,
    )
    expect(screen.getByText('Degraded')).toBeInTheDocument()
    expect(screen.getByText('80% ok (24h)')).toBeInTheDocument()
    expect(
      screen.getByText('Last call failed: HTTP 502 from codex/gpt-5.5'),
    ).toBeInTheDocument()
  })
})
