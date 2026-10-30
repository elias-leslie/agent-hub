import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TokenSharePage from '@/app/token-share/page'
import { fetchSessionHotspots, type SessionHotspots } from '@/lib/api'
import { fetchRequestBlockStats, fetchSessionEfficiency } from '@/lib/api/admin'
import { activityFixture } from './activity-cost-fixture'
import { createQueryClientWrapper } from './test-utils'

vi.mock('@/lib/api', () => ({ fetchSessionHotspots: vi.fn() }))
vi.mock('@/lib/api/admin', () => ({
  fetchRequestBlockStats: vi.fn(),
  fetchSessionEfficiency: vi.fn(),
}))
vi.mock('next/navigation', () => ({
  usePathname: () => '/token-share',
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () =>
    new URLSearchParams(
      'accounting_start=2026-10-21T12:00:00Z&accounting_end=2026-10-22T12:00:00Z',
    ),
}))
vi.mock('@/app/token-share/components/SessionHotspotsPanel', () => ({
  SessionHotspotsPanel: () => <div>Existing session diagnostics</div>,
}))

const hotspots: SessionHotspots = {
  generated_at: activityFixture.window_end,
  window_hours: 24,
  totals: {
    sessions: 4,
    input_tokens: 1000,
    output_tokens: 200,
    total_cost_usd: 1,
    active_sessions: 1,
    zero_event_active_sessions: 0,
    rate_limit_fallback_sessions: 0,
    missing_attribution_sessions: 0,
  },
  attribution_breakdown: [],
  repeated_workloads: [],
  low_yield_sessions: [],
  zero_event_active_sessions: [],
  activity_cost: activityFixture,
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(fetchSessionEfficiency).mockResolvedValue(activityFixture)
  vi.mocked(fetchSessionHotspots).mockResolvedValue(hotspots)
})

function mount() {
  const Wrapper = createQueryClientWrapper()
  return render(
    <Wrapper>
      <TokenSharePage />
    </Wrapper>,
  )
}

describe('Activity page loading', () => {
  it('loads activity when unrelated request-block stats fail', async () => {
    vi.mocked(fetchRequestBlockStats).mockRejectedValue(
      new Error('blocks unavailable'),
    )
    vi.mocked(fetchSessionHotspots).mockResolvedValue(hotspots)
    mount()
    expect(
      screen.getByRole('heading', {
        level: 1,
        name: 'Token share',
      }),
    ).toBeInTheDocument()
    expect(await screen.findByText('50s / 100s')).toBeInTheDocument()
    expect(screen.getByText('Admin + support')).toBeInTheDocument()
    expect(
      screen.getByText(/Request block stats could not be refreshed/),
    ).toBeInTheDocument()
    expect(screen.queryByText('Loading activity…')).not.toBeInTheDocument()
  })

  it('shows an inline error, recovers on retry, and labels retained data after a failed refresh', async () => {
    vi.mocked(fetchRequestBlockStats).mockResolvedValue({
      blocked_requests_today: 0,
      unknown_client_requests_today: 0,
      total_requests_today: 1,
    })
    vi.mocked(fetchSessionEfficiency)
      .mockRejectedValueOnce(new Error('Forbidden (403)'))
      .mockResolvedValueOnce(activityFixture)
      .mockRejectedValue(new Error('Offline'))
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Activity could not be loaded',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Retry activity' }))
    expect(await screen.findByText('50s / 100s')).toBeInTheDocument()
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Refresh token share' }),
      ).not.toBeDisabled(),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Refresh token share' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Showing the last loaded snapshot',
    )
    expect(screen.getByText('50s / 100s')).toBeInTheDocument()
  })
})
