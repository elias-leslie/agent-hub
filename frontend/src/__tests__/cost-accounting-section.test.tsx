import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import {
  CostAccountingSection,
  timeUntil,
} from '@/app/dashboard/components/CostAccountingSection'
import type { CostAccountingResponse } from '@/lib/api'
import { createQueryClientWrapper } from './test-utils'

const data: CostAccountingResponse = {
  as_of: '2026-10-11T17:00:00Z',
  window: { start: '2026-09-12', end: '2026-10-11', days: 30 },
  cash: {
    total_usd: 393.4,
    subscriptions_usd: 392.1,
    metered_api_usd: 1.3,
    credit_purchases_usd: 0,
    month_to_date_usd: 140,
    projected_month_usd: 214,
    subscriptions: [
      {
        provider: 'claude',
        plan: 'max_20x',
        monthly_usd: 200,
        amortized_usd: 197.1,
        days: 30,
      },
      {
        provider: 'codex',
        plan: 'plus',
        monthly_usd: 20,
        amortized_usd: 1.3,
        days: 2,
      },
    ],
    unverified_plans: [],
    daily: [],
  },
  utilization: [
    {
      provider: 'codex',
      plan_type: 'plus',
      windows: [
        {
          window_minutes: 10080,
          label: 'weekly',
          used_percent: 85,
          resets_at: '2099-01-01T00:00:00Z',
          observed_at: '2026-10-11T16:00:00Z',
          reset_since_observed: false,
        },
      ],
    },
  ],
  credits: {
    provider: 'codex',
    used_in_window: 25189,
    balance: 37311,
    burn_per_day_7d: 1500,
    cash_usd_in_window: 0,
    daily: [],
    by_project: [],
    lots: [
      {
        id: 1,
        source: 'grant',
        credits: 62500,
        remaining: 37311,
        remaining_fraction: 0.6,
        granted_at: '2026-09-30T10:29:06Z',
        expires_at: '2026-12-31T23:59:59Z',
        days_to_expiry: 81,
        value_usd_per_credit: 0.04,
        paid_usd: null,
        remaining_value_usd: 1492.44,
        projected_unused_at_expiry: 0,
        evidence: null,
      },
    ],
    attribution_note: '',
  },
  api_equivalent: {
    label: 'API-equivalent value at list price.',
    total_usd: 5120,
    by_provider: [
      {
        provider: 'codex',
        api_equiv_usd: 4000,
        tokens: 1,
        unpriced_tokens: 0,
        fee_usd: 195,
        leverage: 20.5,
      },
    ],
    by_model: [],
    by_project: [
      {
        project: 'agent-hub',
        api_equiv_usd: 3000,
        share: 0.6,
        allocated_fee_usd: 120,
      },
    ],
    by_agent: [],
  },
  alerts: [
    {
      code: 'codex.weekly_high',
      severity: 'warning',
      message: 'Codex weekly limit 85% used',
    },
  ],
}

vi.mock('@/lib/api', () => ({
  fetchCostAccounting: vi.fn(() => Promise.resolve(data)),
}))

describe('CostAccountingSection', () => {
  it('keeps cash, limits, credits and API-equivalent value separate', async () => {
    render(<CostAccountingSection daysRange={30} />, {
      wrapper: createQueryClientWrapper(),
    })
    expect(await screen.findByText('$393')).toBeInTheDocument()
    expect(screen.getByText('Codex weekly limit 85% used')).toBeInTheDocument()
    expect(screen.getByText('weekly 85%')).toBeInTheDocument()
    expect(screen.getByText(/Grant: 37,311 of 62,500 left/)).toBeInTheDocument()
    expect(screen.getByText(/Not money spent/)).toBeInTheDocument()
    expect(screen.getByText('$4,000 (20.5x)')).toBeInTheDocument()
  })

  it('formats time until reset', () => {
    const now = new Date('2026-10-11T00:00:00Z')
    expect(timeUntil('2026-10-11T00:30:00Z', now)).toBe('in 30m')
    expect(timeUntil('2026-10-13T04:00:00Z', now)).toBe('in 2d 4h')
    expect(timeUntil('2026-10-10T00:00:00Z', now)).toBeNull()
  })
})
