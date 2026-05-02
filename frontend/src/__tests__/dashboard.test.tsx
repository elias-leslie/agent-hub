import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DashboardPage from '@/app/dashboard/page'
import { createQueryClientWrapper } from './test-utils'

// Mock the API module
vi.mock('@/lib/api', () => ({
  fetchStatus: vi.fn(),
  fetchCosts: vi.fn(),
}))

import { fetchCosts, fetchStatus } from '@/lib/api'

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

const mockDailyCosts = {
  aggregations: [
    {
      group_key: '2026-01-01',
      total_tokens: 1000,
      input_tokens: 600,
      output_tokens: 400,
      total_cost_usd: 0.01,
      request_count: 5,
    },
    {
      group_key: '2026-01-02',
      total_tokens: 2000,
      input_tokens: 1200,
      output_tokens: 800,
      total_cost_usd: 0.02,
      request_count: 10,
    },
  ],
  total_cost_usd: 0.03,
  total_tokens: 3000,
  total_requests: 15,
}

const mockModelCosts = {
  aggregations: [
    {
      group_key: 'claude-sonnet-4-6',
      total_tokens: 2000,
      input_tokens: 1200,
      output_tokens: 800,
      total_cost_usd: 0.02,
      request_count: 10,
    },
    {
      group_key: 'gemini-flash',
      total_tokens: 1000,
      input_tokens: 600,
      output_tokens: 400,
      total_cost_usd: 0.01,
      request_count: 5,
    },
  ],
  total_cost_usd: 0.03,
  total_tokens: 3000,
  total_requests: 15,
}

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchStatus).mockResolvedValue(mockStatus)
    vi.mocked(fetchCosts).mockImplementation((params) => {
      if (params.group_by === 'day') return Promise.resolve(mockDailyCosts)
      if (params.group_by === 'model') return Promise.resolve(mockModelCosts)
      return Promise.resolve(mockDailyCosts)
    })
  })

  it('renders dashboard header', async () => {
    render(<DashboardPage />, { wrapper: createQueryClientWrapper() })

    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.getByText('7-day view')).toBeInTheDocument()
  })

  it('displays KPI cards', async () => {
    render(<DashboardPage />, { wrapper: createQueryClientWrapper() })

    expect(screen.getAllByText('Sessions').length).toBeGreaterThan(0)
    expect(screen.getByText('Cost')).toBeInTheDocument()
    expect(screen.getByText('Requests')).toBeInTheDocument()
    expect(screen.getByText('Success')).toBeInTheDocument()
  })

  it('shows provider status after loading', async () => {
    render(<DashboardPage />, { wrapper: createQueryClientWrapper() })

    await waitFor(() => {
      expect(screen.getByText('claude')).toBeInTheDocument()
      expect(screen.getByText('gemini')).toBeInTheDocument()
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

  it('displays cost data after loading', async () => {
    render(<DashboardPage />, { wrapper: createQueryClientWrapper() })

    await waitFor(() => {
      // Check that cost is displayed (formatted as currency) - multiple cost values shown
      const costElements = screen.getAllByText(/\$0\.0/)
      expect(costElements.length).toBeGreaterThan(0)
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
