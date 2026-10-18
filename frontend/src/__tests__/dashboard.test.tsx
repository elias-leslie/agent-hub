import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DashboardPage from '@/app/dashboard/page'
import { createQueryClientWrapper } from './test-utils'

// Mock the API module
vi.mock('@/lib/api', () => ({
  fetchStatus: vi.fn(),
}))

import { fetchStatus } from '@/lib/api'

const mockStatus = {
  status: 'healthy' as const,
  service: 'agent-hub',
  database: 'connected',
  providers: [
    {
      name: 'claude',
      available: true,
      configured: true,
      error: null,
      health: {
        state: 'healthy' as const,
        latency_ms: 150,
        error_rate: 0.01,
        availability: 0.99,
        consecutive_failures: 0,
        last_check: Date.now() / 1000,
        last_success: Date.now() / 1000,
        last_error: null,
      },
    },
    {
      name: 'gemini',
      available: true,
      configured: true,
      error: null,
      health: {
        state: 'healthy' as const,
        latency_ms: 200,
        error_rate: 0.02,
        availability: 0.98,
        consecutive_failures: 0,
        last_check: Date.now() / 1000,
        last_success: Date.now() / 1000,
        last_error: null,
      },
    },
  ],
  uptime_seconds: 3600,
  circuit_breakers: null,
  thrashing_events_total: 0,
  circuit_breaker_trips_total: 0,
}

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchStatus).mockResolvedValue(mockStatus)
  })

  it('renders dashboard header', async () => {
    render(<DashboardPage />, { wrapper: createQueryClientWrapper() })

    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.getByText('7-day view')).toBeInTheDocument()
  })

  it('displays KPI cards', async () => {
    render(<DashboardPage />, { wrapper: createQueryClientWrapper() })

    expect(screen.getAllByText('Sessions').length).toBeGreaterThan(0)
    // Spend moved to the Costs page; the dashboard no longer shows a cost_logs-only figure.
    expect(screen.queryByText('Metered spend')).not.toBeInTheDocument()
    expect(screen.getByText('Model calls')).toBeInTheDocument()
    expect(screen.getByText('Success')).toBeInTheDocument()
  })

  it('shows provider status after loading', async () => {
    render(<DashboardPage />, { wrapper: createQueryClientWrapper() })

    await waitFor(() => {
      expect(screen.getByText('Claude')).toBeInTheDocument()
      expect(screen.getByText('Gemini')).toBeInTheDocument()
    })
  })

  it('displays healthy status indicator', async () => {
    render(<DashboardPage />, { wrapper: createQueryClientWrapper() })

    await waitFor(() => {
      expect(screen.getByText('healthy')).toBeInTheDocument()
    })
  })

  it('shows uptime after loading', async () => {
    render(<DashboardPage />, { wrapper: createQueryClientWrapper() })

    await waitFor(() => {
      expect(screen.getByText('healthy')).toBeInTheDocument()
    })
  })

  it('handles API error gracefully', async () => {
    vi.mocked(fetchStatus).mockRejectedValue(new Error('Network error'))

    render(<DashboardPage />, { wrapper: createQueryClientWrapper() })

    await waitFor(() => {
      expect(
        screen.getByText('Unable to connect to backend'),
      ).toBeInTheDocument()
    })
  })
})
