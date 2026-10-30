import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { withLiveOpenCodeGo } from '@/app/costs/components/openCodeGoLive'
import { PlansSection, timeUntil } from '@/app/costs/components/PlansSection'
import type { CostAccountingResponse } from '@/lib/api'
import {
  classifyCreditLot,
  fetchOpenCodeGoUsage,
  type OpenCodeGoUsage,
  type ProviderUtilization,
} from '@/lib/api/analytics'
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
          source: 'workflow_attempt',
          source_label: 'workflow run',
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
      resets_at: '2099-01-01T00:00:00Z',
    },
  ],
}

const storedOpenCode: ProviderUtilization = {
  provider: 'opencode-go',
  plan_type: null,
  windows: [
    {
      window_minutes: 10080,
      label: 'weekly',
      used_percent: 70,
      resets_at: '2099-01-01T00:00:00Z',
      observed_at: '2026-10-11T15:00:00Z',
      reset_since_observed: false,
      source: 'opencode_go_usage',
      source_label: 'OpenCode usage',
    },
  ],
}

const live: OpenCodeGoUsage = {
  provider: 'opencode-go',
  state: 'ok',
  reason: null,
  fetched_at: '2026-10-11T16:59:00Z',
  windows: [
    {
      key: 'rolling',
      label: '5 hours',
      status: 'ok',
      percent: 12,
      resets_at: '2099-01-01T00:00:00Z',
    },
    {
      key: 'weekly',
      label: 'Week',
      status: 'ok',
      percent: 90,
      resets_at: '2099-01-01T00:00:00Z',
    },
    {
      key: 'monthly',
      label: 'Month',
      status: 'rate-limited',
      percent: 100,
      resets_at: null,
    },
  ],
}

vi.mock('@/lib/api', () => ({
  fetchCostAccounting: vi.fn(() => Promise.resolve(data)),
}))

vi.mock('@/lib/api/analytics', async (original) => ({
  ...(await original<typeof import('@/lib/api/analytics')>()),
  fetchOpenCodeGoUsage: vi.fn(),
  classifyCreditLot: vi.fn(() => Promise.resolve()),
}))

function renderPlans(liveResult: OpenCodeGoUsage | Error) {
  vi.mocked(fetchOpenCodeGoUsage).mockImplementation(() =>
    liveResult instanceof Error
      ? Promise.reject(liveResult)
      : Promise.resolve(liveResult),
  )
  render(<PlansSection daysRange={30} />, {
    wrapper: createQueryClientWrapper(),
  })
}

describe('PlansSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    data.utilization = data.utilization.filter(
      (p) => p.provider !== 'opencode-go',
    )
  })

  it('keeps cash, plan limits and credits separate', async () => {
    vi.mocked(fetchOpenCodeGoUsage).mockReturnValue(new Promise(() => {}))
    render(<PlansSection daysRange={30} />, {
      wrapper: createQueryClientWrapper(),
    })
    expect(await screen.findByText('$393')).toBeInTheDocument()
    expect(
      screen.getByText(/^Codex weekly limit 85% used; resets in \d+d \d+h$/),
    ).toBeInTheDocument()
    expect(screen.getByText('weekly 85%')).toBeInTheDocument()
    expect(screen.getByText(/workflow run ·/)).toBeInTheDocument()
    expect(screen.getByText(/Grant: 37,311 of 62,500 left/)).toBeInTheDocument()
    expect(screen.queryByText(/Not money spent/)).not.toBeInTheDocument()
  })

  it('records detected credits as a grant or a purchase from the alert', async () => {
    vi.mocked(fetchOpenCodeGoUsage).mockReturnValue(new Promise(() => {}))
    const saved = data.alerts
    data.alerts = [
      {
        code: 'codex.lot_unclassified',
        severity: 'warning',
        lot_id: 2,
        message: 'New Codex credits detected (12,500): granted or purchased?',
      },
    ]
    try {
      render(<PlansSection daysRange={30} />, {
        wrapper: createQueryClientWrapper(),
      })
      await screen.findByText(/New Codex credits detected/)

      fireEvent.click(screen.getByRole('button', { name: 'Granted' }))
      await waitFor(() =>
        expect(vi.mocked(classifyCreditLot)).toHaveBeenCalledWith(2, {
          source: 'grant',
        }),
      )

      fireEvent.click(screen.getByRole('button', { name: 'Purchased…' }))
      expect(screen.getByLabelText('Paid $')).toHaveFocus()
      const save = screen.getByRole('button', { name: 'Save purchase' })
      expect(save).toBeDisabled()
      fireEvent.change(screen.getByLabelText('Paid $'), {
        target: { value: '40' },
      })
      fireEvent.click(save)
      await waitFor(() =>
        expect(vi.mocked(classifyCreditLot)).toHaveBeenLastCalledWith(2, {
          source: 'purchase',
          paid_usd: 40,
        }),
      )
    } finally {
      data.alerts = saved
    }
  })

  it('reads one day as "last day" and prices cents like the rest of Costs', async () => {
    vi.mocked(fetchOpenCodeGoUsage).mockReturnValue(new Promise(() => {}))
    const saved = { window: data.window, cash: data.cash }
    data.window = { ...data.window, days: 1 }
    data.cash = { ...data.cash, metered_api_usd: 0.66 }
    try {
      render(<PlansSection daysRange={1} />, {
        wrapper: createQueryClientWrapper(),
      })
      expect(await screen.findByText('Cash, last day')).toBeInTheDocument()
      expect(screen.getByText('Used, last day')).toBeInTheDocument()
      expect(screen.getByText('$0.66')).toBeInTheDocument()
    } finally {
      Object.assign(data, saved)
    }
  })

  it('names plans the way the provider sells them', async () => {
    vi.mocked(fetchOpenCodeGoUsage).mockReturnValue(new Promise(() => {}))
    const saved = data.cash
    data.cash = {
      ...data.cash,
      subscriptions: [
        ...data.cash.subscriptions,
        {
          provider: 'opencode-go',
          plan: 'go',
          monthly_usd: 40,
          amortized_usd: 9.4,
          days: 7,
        },
      ],
    }
    try {
      render(<PlansSection daysRange={30} />, {
        wrapper: createQueryClientWrapper(),
      })
      expect(
        await screen.findByText('Claude Code Max 20x at $200/mo'),
      ).toBeInTheDocument()
      expect(screen.getByText('Codex Plus at $20/mo')).toBeInTheDocument()
      expect(screen.getByText('OpenCode Go at $40/mo')).toBeInTheDocument()
    } finally {
      data.cash = saved
    }
  })

  it('shows OpenCode Go once in plan limits, live when OpenCode answers', async () => {
    data.utilization = [...data.utilization, storedOpenCode]
    renderPlans(live)
    expect(await screen.findByText('5h 12%')).toBeInTheDocument()
    expect(screen.getAllByText('OpenCode Go')).toHaveLength(1)
    expect(screen.getByText('weekly 90%')).toBeInTheDocument()
    expect(screen.queryByText('weekly 70%')).not.toBeInTheDocument()
    expect(screen.getByText('Rate limited')).toBeInTheDocument()
    expect(screen.getAllByText(/OpenCode, live ·/)).toHaveLength(3)
    expect(screen.getByText(/unofficial OpenCode endpoint/)).toBeInTheDocument()
    expect(
      screen.getByRole('meter', { name: 'OpenCode Go monthly used' }),
    ).toHaveAttribute('aria-valuetext', '100%, rate limited')
  })

  it('falls back to the stored OpenCode Go reading with its age when live fails', async () => {
    data.utilization = [...data.utilization, storedOpenCode]
    renderPlans({
      ...live,
      state: 'unavailable',
      reason: 'Could not reach OpenCode.',
      windows: [],
    })
    const note = await screen.findByText(
      'Live reading unavailable. Could not reach OpenCode.',
    )
    const block = note.parentElement as HTMLElement
    expect(within(block).getByText('weekly 70%')).toBeInTheDocument()
    expect(within(block).getByText(/OpenCode usage ·/)).toBeInTheDocument()
  })

  it('says when OpenCode Go is not set up and nothing is stored', async () => {
    renderPlans({
      ...live,
      state: 'not_configured',
      reason: 'No OpenCode Go API key is set for Agent Hub.',
      windows: [],
    })
    expect(
      await screen.findByText(
        'Not set up. No OpenCode Go API key is set for Agent Hub.',
      ),
    ).toBeInTheDocument()
  })

  it('keeps stored readings while the live request is loading or after it errors', () => {
    const stored = [...data.utilization, storedOpenCode]
    expect(withLiveOpenCodeGo(stored, undefined, false)).toEqual(stored)
    const failed = withLiveOpenCodeGo(stored, undefined, true)
    expect(failed.at(-1)?.windows).toEqual(storedOpenCode.windows)
    expect(failed.at(-1)?.note).toBe('Live reading unavailable.')
    expect(withLiveOpenCodeGo(data.utilization, undefined, false)).toEqual(
      data.utilization,
    )
    expect(withLiveOpenCodeGo(stored, live, true).at(-1)?.note).toMatch(
      /^Live refresh failed; showing the last live reading\./,
    )
  })

  it('formats time until reset', () => {
    const now = new Date('2026-10-11T00:00:00Z')
    expect(timeUntil('2026-10-11T00:30:00Z', now)).toBe('in 30m')
    expect(timeUntil('2026-10-13T04:00:00Z', now)).toBe('in 2d 4h')
    expect(timeUntil('2026-10-10T00:00:00Z', now)).toBeNull()
  })
})
