import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import {
  fetchSpendPatterns,
  type SpendPatternsResponse,
} from '@/lib/api/analytics'
import { SpendPatternsSection } from './SpendPatternsSection'

vi.mock('@/lib/api/analytics', () => ({ fetchSpendPatterns: vi.fn() }))

const DATA: SpendPatternsResponse = {
  window_days: 7,
  generated_at: '2026-10-17T00:00:00Z',
  unavailable: ['repeated_calls'],
  unpriced: {
    calls: 170,
    unpriced_calls: 4,
    models: [{ model: 'mystery-1', calls: 4, tokens: 900 }],
  },
  effort: {
    levels: [
      { effort: 'xhigh', sessions: 6, tokens: 0 },
      { effort: 'medium', sessions: 4, tokens: 0 },
    ],
    sessions_with_effort: 10,
    high_session_share: 0.6,
    high_token_share: null,
  },
  model_names: {
    sessions: 31,
    names: [{ model: 'opus', kind: 'alias, not a model', sessions: 31 }],
  },
  empty_sessions: { sessions: 0, by_source: [] },
  repeated_calls: null,
  gated_automations: {
    enabled: 10,
    gated: [
      {
        label: 'Nightly Screen',
        project: 'jobinator-4000',
        reasons: ['project_disabled'],
      },
    ],
  },
  weekly_spike: {
    measure: 'cash',
    current: 3,
    usual: 1,
    ratio: 3,
    spike: true,
  },
}

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <SpendPatternsSection daysRange={7} />
    </QueryClientProvider>,
  )
}

describe('SpendPatternsSection', () => {
  it('shows each pattern in plain words and marks the missing one', async () => {
    vi.mocked(fetchSpendPatterns).mockResolvedValue(DATA)
    renderSection()

    expect(
      await screen.findByText('Spend is 3x the usual for 7 days.'),
    ).toBeTruthy()
    expect(
      screen.getByText('4 of 170 calls used tokens but have no price.'),
    ).toBeTruthy()
    expect(screen.getByText(/60% of sessions ran at xhigh or max/)).toBeTruthy()
    expect(screen.getByText('opus (alias, not a model)')).toBeTruthy()
    expect(
      screen.getByText('No sessions ended with nothing in them.'),
    ).toBeTruthy()
    expect(screen.getByText("Couldn't load this one.")).toBeTruthy()
    expect(
      screen.getByText("1 of 10 turned-on automations can't run."),
    ).toBeTruthy()
    expect(screen.getByText('project automations off')).toBeTruthy()
  })

  it('says so when the whole view fails', async () => {
    vi.mocked(fetchSpendPatterns).mockRejectedValue(new Error('boom'))
    renderSection()
    expect(
      await screen.findByText(/Spend patterns unavailable: boom/),
    ).toBeTruthy()
  })
})
