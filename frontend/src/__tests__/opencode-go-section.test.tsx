import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { OpenCodeGoSection } from '@/app/costs/components/OpenCodeGoSection'
import type { OpenCodeGoUsage } from '@/lib/api/analytics'
import { fetchOpenCodeGoUsage } from '@/lib/api/analytics'
import { createQueryClientWrapper } from './test-utils'

vi.mock('@/lib/api/analytics', async (original) => ({
  ...(await original<typeof import('@/lib/api/analytics')>()),
  fetchOpenCodeGoUsage: vi.fn(),
}))

const base: OpenCodeGoUsage = {
  provider: 'opencode-go',
  state: 'ok',
  reason: null,
  fetched_at: '2026-10-23T12:00:00Z',
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
      percent: 85,
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

function show(data: OpenCodeGoUsage | Error) {
  vi.mocked(fetchOpenCodeGoUsage).mockImplementation(() =>
    data instanceof Error ? Promise.reject(data) : Promise.resolve(data),
  )
  render(<OpenCodeGoSection />, { wrapper: createQueryClientWrapper() })
}

describe('OpenCodeGoSection', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows each window with percent, status and reset', async () => {
    show(base)
    expect(await screen.findByText('5 hours')).toBeTruthy()
    expect(screen.getByText('12%')).toBeTruthy()
    expect(screen.getByText('85%')).toBeTruthy()
    expect(screen.getByText('Rate limited')).toBeTruthy()
    expect(screen.getAllByText(/^Resets in /)).toHaveLength(2)
    expect(screen.getAllByRole('meter')).toHaveLength(3)
    expect(screen.getByText(/unofficial endpoint/)).toBeTruthy()
  })

  it('says so when OpenCode is unavailable', async () => {
    show({
      ...base,
      state: 'unavailable',
      reason: 'Could not reach OpenCode.',
      windows: [],
    })
    expect(await screen.findByText('Unavailable')).toBeTruthy()
    expect(screen.getByText('Could not reach OpenCode.')).toBeTruthy()
    expect(screen.queryByRole('meter')).toBeNull()
  })

  it('says when no key is set up', async () => {
    show({
      ...base,
      state: 'not_configured',
      reason: 'No OpenCode Go API key is set for Agent Hub.',
      windows: [],
    })
    expect(await screen.findByText('Not set up')).toBeTruthy()
  })

  it('shows unavailable when the request fails', async () => {
    show(new Error('boom'))
    expect(await screen.findByText('Unavailable')).toBeTruthy()
  })
})
