import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AdminPage from '@/app/admin/page'
import { fetchSessionHotspots, type SessionHotspots } from '@/lib/api'
import { fetchRequestBlockStats } from '@/lib/api/admin'
import { activityFixture } from './activity-cost-fixture'

vi.mock('@/lib/api', () => ({ fetchSessionHotspots: vi.fn() }))
vi.mock('@/lib/api/admin', () => ({ fetchRequestBlockStats: vi.fn() }))
vi.mock('@/app/admin/components/SessionHotspotsPanel', () => ({
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

beforeEach(() => vi.resetAllMocks())

describe('Activity page loading', () => {
  it('loads activity when unrelated request-block stats fail', async () => {
    vi.mocked(fetchRequestBlockStats).mockRejectedValue(
      new Error('blocks unavailable'),
    )
    vi.mocked(fetchSessionHotspots).mockResolvedValue(hotspots)
    render(<AdminPage />)
    expect(
      screen.getByRole('heading', {
        level: 1,
        name: 'Work and admin activity',
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
    vi.mocked(fetchSessionHotspots)
      .mockRejectedValueOnce(new Error('Forbidden (403)'))
      .mockResolvedValueOnce(hotspots)
      .mockRejectedValue(new Error('Offline'))
    render(<AdminPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Activity could not be loaded',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Retry activity' }))
    expect(await screen.findByText('50s / 100s')).toBeInTheDocument()
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Refresh activity data' }),
      ).not.toBeDisabled(),
    )
    fireEvent.click(
      screen.getByRole('button', { name: 'Refresh activity data' }),
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Showing the last loaded snapshot',
    )
    expect(screen.getByText('50s / 100s')).toBeInTheDocument()
  })
})
